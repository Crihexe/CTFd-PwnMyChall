from CTFd.plugins import challenges, register_plugin_assets_directory
from flask_restx import Namespace, Resource
from flask import session, Blueprint, abort, jsonify, redirect, url_for, request, render_template
from CTFd.cache import clear_challenges, clear_standings
from CTFd.models import db, Challenges, Users, Hints, ChallengeFiles, Awards, Solves, Tags, Flags, Fails
from CTFd.schemas.flags import FlagSchema
from CTFd.schemas.tags import TagSchema
from CTFd.utils.uploads import delete_file
from CTFd.utils import uploads
from logging import basicConfig, getLogger, DEBUG, ERROR
from CTFd.plugins.migrations import upgrade
from CTFd.plugins.challenges import get_chal_class
from CTFd.api import CTFd_API_v1
from CTFd.plugins.dynamic_challenges.decay import DECAY_FUNCTIONS, logarithmic, get_solve_count
from CTFd.utils.user import get_current_user, authed, is_admin
from pathlib import Path
from CTFd.utils.plugins import override_template, register_script
from CTFd.utils.decorators import (
    admins_only,
    authed_only,
    during_ctf_time_only,
    require_verified_emails,
)
from CTFd.utils.decorators.visibility import (
    check_account_visibility,
    check_challenge_visibility,
    check_score_visibility,
)
from CTFd.utils.scores import get_user_standings


basicConfig(level=DEBUG)
logger = getLogger(__name__)

restful = Blueprint('pwnmychall', __name__)
pwnmychall_pages = Blueprint(
    "pwnmychall_pages",
    __name__,
    template_folder="templates",
)

PWNMYCHALL_DEFAULTS = {
    "function": "logarithmic",
    "decay": 10,
    "max_reward": 100,
    "min_reward": 10,
    "max_threshold": 10,
    "min_threshold": 60,
}


def _get_current_user_or_403():
    user = get_current_user()
    if not user:
        abort(403)
    return user


def _discord_id_from_email(email):
    if not isinstance(email, str):
        return None
    normalized = email.strip().lower()
    prefix = "discord+"
    suffix = "@avctf.local"
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        return None
    candidate = normalized[len(prefix):-len(suffix)]
    if candidate.isdigit():
        return candidate
    return None


def _normalize_creator(creator_value):
    creator = str(creator_value or "").strip()
    if creator.lower().startswith("discord:"):
        creator = creator.split(":", 1)[1].strip()
    return creator


def _resolve_creator_user(challenge):
    creator = _normalize_creator(getattr(challenge, "creator", None))
    if not creator:
        return None
    if creator.isdigit():
        by_email = Users.query.filter_by(email=f"discord+{creator}@avctf.local").first()
        if by_email is not None:
            return by_email
    return Users.query.filter_by(name=creator).first()


def _is_creator_user(user, challenge):
    if user is None or challenge is None:
        return False
    creator = _normalize_creator(getattr(challenge, "creator", None))
    if not creator:
        return False
    if creator == str(getattr(user, "name", "") or ""):
        return True
    discord_id = _discord_id_from_email(getattr(user, "email", None))
    if discord_id and creator == discord_id:
        return True
    creator_user = _resolve_creator_user(challenge)
    return bool(creator_user and creator_user.id == user.id)


def _creator_reference_for_user(user):
    discord_id = _discord_id_from_email(getattr(user, "email", None))
    if discord_id:
        return discord_id
    return str(getattr(user, "name", "") or "")


def _user_can_manage_challenge(user, challenge):
    return is_admin() or _is_creator_user(user, challenge)


def _get_owned_challenge(challenge_id):
    challenge = PwnMyChall.query.filter_by(id=challenge_id).first_or_404()
    user = _get_current_user_or_403()
    if not _user_can_manage_challenge(user, challenge):
        abort(403)
    return challenge, user


def _serialize_pwnmychall_summary(challenge):
    award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
    solves = get_solve_count(challenge)
    return {
        "id": challenge.id,
        "name": challenge.name,
        "category": challenge.category,
        "state": challenge.state,
        "value": challenge.value,
        "solves": solves,
        "reward": award.value if award else None,
    }


def _serialize_pwnmychall_detail(challenge):
    data = _serialize_pwnmychall_summary(challenge)
    data.update(
        {
            "description": challenge.description,
            "initial": challenge.initial,
            "minimum": challenge.minimum,
        }
    )
    return data

class PwnMyChallAward(Awards):
    __mapper_args__ = {'polymorphic_identity': 'pwnmychallaward'}
    id = db.Column(
        db.Integer, db.ForeignKey("awards.id", ondelete="CASCADE"), primary_key=True
    )
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"))

    def __init__(self, user_id, name, value, challenge_id):
        self.user_id = user_id
        self.type = "pwnmychallaward"
        self.name = name
        self.description = "The points given to the challenge creator based on solves"
        self.value = value
        self.challenge_id = challenge_id

class PwnMyChall(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'pwnmychall'}
    id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    initial = db.Column(db.Integer, default=0)
    minimum = db.Column(db.Integer, default=0)
    decay = db.Column(db.Integer, default=0)
    function = db.Column(db.String(32), default="logarithmic")
    creator = db.Column(db.String(64))
    max_reward = db.Column(db.Integer)
    min_reward = db.Column(db.Integer)
    max_threshold = db.Column(db.Integer)
    min_threshold = db.Column(db.Integer)
    

    def __init__(self, name, description, category, state, initial, minimum, decay, function, creator, max_reward, min_reward, min_threshold, max_threshold, type='pwnmychall'):
        self.name = name
        self.description = description
        self.category = category
        self.state = state
        self.initial = initial
        self.value = initial
        self.minimum = minimum
        self.decay = decay
        self.function = function
        self.creator = creator
        self.max_reward = max_reward
        self.min_reward = min_reward
        self.max_threshold = max_threshold
        self.min_threshold = min_threshold
        self.type = type

class CTFdPwnMyChall(challenges.BaseChallenge):
    id = "pwnmychall"
    name = "pwnmychall"

    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/CTFd-PwnMyChall/assets/create.html',
        'update': '/plugins/CTFd-PwnMyChall/assets/update.html',
        'view': '/plugins/CTFd-PwnMyChall/assets/view.html',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/CTFd-PwnMyChall/assets/create.js',
        'update': '/plugins/CTFd-PwnMyChall/assets/update.js',
        'view': '/plugins/CTFd-PwnMyChall/assets/view.js',
    }
    route = '/plugins/CTFd-PwnMyChall/assets'
    challenge_model = PwnMyChall

    @classmethod
    def calculate_dynamic_value(cls, challenge):
        f = DECAY_FUNCTIONS.get(challenge.function, logarithmic)
        value = f(challenge)

        challenge.value = value
        db.session.commit()
        return challenge
    
    @classmethod
    def calculate_reward_value(cls, challenge):
        solves = get_solve_count(challenge)

        max_threshold = challenge.max_threshold/100.0
        min_threshold = challenge.min_threshold/100.0
        
        players = float(len(get_user_standings())) # per sicurezza il vero numero di player totale giocanti, lo trovo vedendo la query della classifica, siccome il db e' un po' strano e bisognerebbe capire quali Users sono player e quali no

        value = 0
        if solves < 1:
            value = challenge.min_reward
        elif 1 <= solves and solves <= max_threshold*players:
            value = challenge.max_reward
        elif solves >= min_threshold*players:
            value = challenge.min_reward
        elif max_threshold*players < solves and solves < min_threshold*players:
            z = ( (100*solves)/players - challenge.max_threshold )*( 1/(challenge.min_threshold-challenge.max_threshold) )
            z2 = z*z
            value = -1*(z2/(2*(z2-z)+1))*(challenge.max_reward-challenge.min_reward)+challenge.max_reward

        
        award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
        if award is None:
            creator_user = _resolve_creator_user(challenge)
            award = PwnMyChallAward(
                user_id=creator_user.id if creator_user is not None else None,
                name=challenge.id,
                challenge_id=challenge.id,
                value=challenge.min_reward,
            )
            db.session.add(award)

        award.value = value
        creator_user = _resolve_creator_user(challenge)
        award.user_id = creator_user.id if creator_user is not None else None
        
        db.session.commit()
        return challenge
        
    @classmethod
    def getCreatorUser(cls, challenge):
        return _resolve_creator_user(challenge)

    @classmethod
    def create(cls, request):
        data = request.form or request.get_json()
        challenge_data = {key:value for (key,value) in data.items()}

        challenge = PwnMyChall(**challenge_data)

        if 'hidden' in request.form:
            challenge.hidden = True
        else:
            challenge.hidden = False

        db.session.add(challenge)

        rewarded_user = None
        user = CTFdPwnMyChall.getCreatorUser(challenge)
        if user:
            rewarded_user = user.id

        award = PwnMyChallAward(user_id=rewarded_user, name=challenge.id, challenge_id=challenge.id, value=challenge.min_reward)    # cosi' siamo sicuri di avere un reward per ogni challenge
        db.session.add(award)
        
        db.session.commit()

        return challenge
    
    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()

        for attr, value in data.items():
            # We need to set these to floats so that the next operations don't operate on strings
            if attr in ("initial", "minimum", "decay", "max_reward", "min_reward", "max_threshold", "min_threshold"):
                value = float(value)
            setattr(challenge, attr, value)

        return CTFdPwnMyChall.calculate_dynamic_value(challenge)

    @classmethod
    def read(cls, challenge):
        challenge = PwnMyChall.query.filter_by(id=challenge.id).first()
        data = {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "initial": challenge.initial,
            "decay": challenge.decay,
            "minimum": challenge.minimum,
            "function": challenge.function,
            "description": challenge.description,
            ##############################
            "created_by_me": _is_creator_user(get_current_user(), challenge),
            # forse questi due dovrebbero essere configurabili se visiibli ai player o no
            # per evitare favoritismi tra player non so
            "creator": challenge.creator,
            "max_reward": challenge.max_reward,
            "min_reward": challenge.min_reward,
            "max_threshold": challenge.max_threshold,
            "min_threshold": challenge.min_threshold,
            ##############################
            "attribution": challenge.attribution,
            "connection_info": challenge.connection_info,
            "next_id": challenge.next_id,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            "type_data": {
                "id": cls.id,
                "name": cls.name,
                "templates": cls.templates,
                "scripts": cls.scripts,
            },
        }
        return data
    @classmethod
    def delete(cls, challenge):
        pmcAward = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
        Awards.query.filter_by(id=pmcAward.id).delete()
        PwnMyChall.query.filter_by(id=challenge.id).delete()
        super().delete(challenge)

    @classmethod
    def attempt(cls, challenge, request):
        user = get_current_user()

        CTFdPwnMyChall.calculate_reward_value(challenge)

        chal_class = get_chal_class(challenge.type)
        pwnmychall = challenge
        if chal_class is not PwnMyChall:
            pwnmychall = PwnMyChall.query.filter_by(id=challenge.id).first()
        
        if _is_creator_user(user, pwnmychall):
            return False, "You are the creator, you can't pwn me!"

        return super().attempt(challenge, request)

    @classmethod
    def solve(cls, user, team, challenge, request):
        """
        This method is used to insert Solves into the database in order to mark a challenge as solved.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """

        chal_class = get_chal_class(challenge.type)
        pwnmychall = challenge
        if chal_class is not PwnMyChall:
            pwnmychall = PwnMyChall.query.filter_by(id=challenge.id).first()
        
        if _is_creator_user(user, pwnmychall):  # se chi ha creato la chall prova a risolversela, errore
            return
        else:
            super().solve(user, team, challenge, request)

            CTFdPwnMyChall.calculate_dynamic_value(challenge)
            CTFdPwnMyChall.calculate_reward_value(challenge)

pwnmychall_namespace = Namespace("pwnmychall", description="PwnMyChall Endpoints")

@pwnmychall_namespace.route("/challenges/byme")
class Challenge(Resource):
    @check_challenge_visibility
    @during_ctf_time_only
    @require_verified_emails
    def get(self):
        if authed():
            user = get_current_user()
        else:
            return {"success": False, "error": "User not authed."}

        challs = PwnMyChall.query.all()
        data = []
        for c in challs:
            if _is_creator_user(user, c):
                data.append(c.id)
        return {"success": True, "data": data}

@pwnmychall_namespace.route("/challenges/<chal_id>/byme")
class Challenge(Resource):
    @check_challenge_visibility
    @during_ctf_time_only
    @require_verified_emails
    def get(self, chal_id):
        if authed():
            user = get_current_user()
        else:
            return {"success": False, "error": "User not authed."}

        chal = PwnMyChall.query.filter_by(id=chal_id).first()
        if chal is None:
            return {"success": False, "error": "Challenge not found."}, 404
        
        return {"success": True, "data": _is_creator_user(user, chal)}

@pwnmychall_namespace.route("/awards/bind/<chal_id>")
class Award(Resource):
    @require_verified_emails
    def get(self, chal_id): # mi dispiace :( non ne ho mezza basta che funziona
        if not authed():
            return {"success": False, "error": "User not authed."}
        
        challenge = PwnMyChall.query.filter_by(id=chal_id).first()
        if challenge is None:
            return {"success": False, "error": "Challenge not found"}, 404

        award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
        if award is None:
            return {"success": False, "error": "Award not found for this challenge"}, 404

        user = _resolve_creator_user(challenge)
        if user is None:
            award.user_id = None
            db.session.commit()
            return {
                "success": True,
                "data": {
                    "name": None,
                    "id": None,
                    "bound": False,
                    "message": "Creator account not found. Award left unbound.",
                },
            }

        award.user_id = user.id
        db.session.commit()

        return {"success": True, "data": {"name": user.name, "id": user.id, "bound": True}}


@pwnmychall_namespace.route("/challenges")
class PwnMyChallChallengeList(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self):
        user = _get_current_user_or_403()
        query = PwnMyChall.query
        challenges_data = query.all()
        if not is_admin():
            challenges_data = [c for c in challenges_data if _is_creator_user(user, c)]
        data = [_serialize_pwnmychall_summary(c) for c in challenges_data]
        return {"success": True, "data": data}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def post(self):
        user = _get_current_user_or_403()
        data = request.get_json() or request.form or {}

        name = data.get("name")
        category = data.get("category")
        description = data.get("description", "")
        state = data.get("state", "hidden")
        initial = data.get("initial")
        minimum = data.get("minimum")

        errors = {}
        if not name:
            errors["name"] = ["Name is required"]
        if not category:
            errors["category"] = ["Category is required"]
        if initial is None:
            errors["initial"] = ["Initial value is required"]
        if minimum is None:
            errors["minimum"] = ["Minimum value is required"]
        if errors:
            return {"success": False, "errors": errors}, 400

        try:
            initial = float(initial)
            minimum = float(minimum)
        except (TypeError, ValueError):
            return {
                "success": False,
                "errors": {"initial": ["Initial and minimum must be numbers"]},
            }, 400

        if state not in ("visible", "hidden"):
            state = "hidden"

        challenge = PwnMyChall(
            name=name,
            description=description,
            category=category,
            state=state,
            initial=initial,
            minimum=minimum,
            decay=PWNMYCHALL_DEFAULTS["decay"],
            function=PWNMYCHALL_DEFAULTS["function"],
            creator=_creator_reference_for_user(user),
            max_reward=PWNMYCHALL_DEFAULTS["max_reward"],
            min_reward=PWNMYCHALL_DEFAULTS["min_reward"],
            min_threshold=PWNMYCHALL_DEFAULTS["min_threshold"],
            max_threshold=PWNMYCHALL_DEFAULTS["max_threshold"],
        )

        db.session.add(challenge)
        db.session.flush()

        award = PwnMyChallAward(
            user_id=user.id,
            name=challenge.id,
            challenge_id=challenge.id,
            value=challenge.min_reward,
        )
        db.session.add(award)
        db.session.commit()

        clear_challenges()

        return {"success": True, "data": _serialize_pwnmychall_detail(challenge)}


@pwnmychall_namespace.route("/challenges/<int:challenge_id>")
class PwnMyChallChallengeDetail(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        return {"success": True, "data": _serialize_pwnmychall_detail(challenge)}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def patch(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        data = request.get_json() or {}

        allowed_fields = {"name", "category", "description", "state", "initial", "minimum"}
        for attr, value in data.items():
            if attr not in allowed_fields:
                continue
            if attr in ("initial", "minimum"):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return {"success": False, "errors": {attr: ["Must be a number"]}}, 400
            if attr == "state" and value not in ("visible", "hidden"):
                continue
            setattr(challenge, attr, value)

        CTFdPwnMyChall.calculate_dynamic_value(challenge)
        CTFdPwnMyChall.calculate_reward_value(challenge)

        clear_standings()
        clear_challenges()

        return {"success": True, "data": _serialize_pwnmychall_detail(challenge)}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def delete(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        chal_class = get_chal_class(challenge.type)
        chal_class.delete(challenge)

        clear_standings()
        clear_challenges()

        return {"success": True}


@pwnmychall_namespace.route("/challenges/<int:challenge_id>/flags")
class PwnMyChallChallengeFlags(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        schema = FlagSchema(many=True)
        response = schema.dump(flags)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400
        return {"success": True, "data": response.data}


@pwnmychall_namespace.route("/flags/types")
class PwnMyChallFlagTypes(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self):
        response = {}
        from CTFd.plugins.flags import FLAG_CLASSES

        for class_id in FLAG_CLASSES:
            flag_class = FLAG_CLASSES.get(class_id)
            response[class_id] = {
                "name": flag_class.name,
                "templates": flag_class.templates,
            }
        return {"success": True, "data": response}


@pwnmychall_namespace.route("/flags")
class PwnMyChallFlags(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def post(self):
        req = request.get_json() or {}
        challenge_id = req.get("challenge_id") or req.get("challenge")
        if not challenge_id:
            return {"success": False, "errors": {"challenge": ["Missing challenge id"]}}, 400

        challenge, _user = _get_owned_challenge(int(challenge_id))

        schema = FlagSchema()
        if req.get("type") in ("static", "regex") and req.get("content"):
            req["content"] = req["content"].strip()

        req["challenge_id"] = challenge.id
        req.pop("challenge", None)

        response = schema.load(req, session=db.session)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400

        db.session.add(response.data)
        db.session.commit()

        response = schema.dump(response.data)
        db.session.close()
        return {"success": True, "data": response.data}


@pwnmychall_namespace.route("/flags/<int:flag_id>")
class PwnMyChallFlag(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self, flag_id):
        flag = Flags.query.filter_by(id=flag_id).first_or_404()
        _get_owned_challenge(flag.challenge_id)
        schema = FlagSchema()
        response = schema.dump(flag)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400
        return {"success": True, "data": response.data}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def patch(self, flag_id):
        flag = Flags.query.filter_by(id=flag_id).first_or_404()
        _get_owned_challenge(flag.challenge_id)

        req = request.get_json() or {}
        schema = FlagSchema()

        if flag.type in ("static", "regex") and req.get("content"):
            req["content"] = req["content"].strip()

        req.pop("challenge", None)
        req.pop("challenge_id", None)
        req.pop("type", None)

        response = schema.load(req, session=db.session, instance=flag, partial=True)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400

        db.session.commit()
        response = schema.dump(response.data)
        db.session.close()
        return {"success": True, "data": response.data}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def delete(self, flag_id):
        flag = Flags.query.filter_by(id=flag_id).first_or_404()
        _get_owned_challenge(flag.challenge_id)
        db.session.delete(flag)
        db.session.commit()
        db.session.close()
        return {"success": True}


@pwnmychall_namespace.route("/challenges/<int:challenge_id>/tags")
class PwnMyChallChallengeTags(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        tags = Tags.query.filter_by(challenge_id=challenge.id).all()
        response = [{"id": t.id, "challenge_id": t.challenge_id, "value": t.value} for t in tags]
        return {"success": True, "data": response}


@pwnmychall_namespace.route("/tags")
class PwnMyChallTags(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def post(self):
        req = request.get_json() or {}
        challenge_id = req.get("challenge_id") or req.get("challenge")
        if not challenge_id:
            return {"success": False, "errors": {"challenge": ["Missing challenge id"]}}, 400

        challenge, _user = _get_owned_challenge(int(challenge_id))
        schema = TagSchema()
        req["challenge_id"] = challenge.id
        req.pop("challenge", None)
        response = schema.load(req, session=db.session)
        if response.errors:
            return {"success": False, "errors": response.errors}, 400

        db.session.add(response.data)
        db.session.commit()
        response = schema.dump(response.data)
        db.session.close()
        return {"success": True, "data": response.data}


@pwnmychall_namespace.route("/tags/<int:tag_id>")
class PwnMyChallTag(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def delete(self, tag_id):
        tag = Tags.query.filter_by(id=tag_id).first_or_404()
        _get_owned_challenge(tag.challenge_id)
        db.session.delete(tag)
        db.session.commit()
        db.session.close()
        return {"success": True}


@pwnmychall_namespace.route("/challenges/<int:challenge_id>/files")
class PwnMyChallChallengeFiles(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def get(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        response = [
            {"id": f.id, "type": f.type, "location": f.location, "sha1sum": f.sha1sum}
            for f in files
        ]
        return {"success": True, "data": response}

    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def post(self, challenge_id):
        challenge, _user = _get_owned_challenge(challenge_id)
        files = request.files.getlist("file")
        location = request.form.get("location")

        if len(files) > 1 and location:
            return {
                "success": False,
                "errors": {"location": ["Location cannot be specified with multiple files"]},
            }, 400

        objs = []
        for f in files:
            try:
                obj = uploads.upload_file(
                    file=f, challenge_id=challenge.id, type="challenge", location=location
                )
            except ValueError as e:
                return {"success": False, "errors": {"location": [str(e)]}}, 400
            objs.append(obj)

        response = [
            {"id": f.id, "type": f.type, "location": f.location, "sha1sum": f.sha1sum}
            for f in objs
        ]
        return {"success": True, "data": response}


@pwnmychall_namespace.route("/files/<int:file_id>")
class PwnMyChallFile(Resource):
    @authed_only
    @during_ctf_time_only
    @require_verified_emails
    def delete(self, file_id):
        f = ChallengeFiles.query.filter_by(id=file_id).first_or_404()
        _get_owned_challenge(f.challenge_id)
        delete_file(file_id=f.id)
        return {"success": True}


@pwnmychall_pages.route("/pwnmychall/dashboard")
@authed_only
def pwnmychall_dashboard():
    return render_template("pwnmychall_dashboard.html")


@pwnmychall_pages.route("/pwnmychall/challenges/new")
@authed_only
def pwnmychall_create():
    return render_template("pwnmychall_create.html")


@pwnmychall_pages.route("/pwnmychall/challenges/<int:challenge_id>/edit")
@authed_only
def pwnmychall_edit(challenge_id):
    return render_template("pwnmychall_edit.html", challenge_id=challenge_id)

def override_challenges_template():
    dir_path = Path(__file__).parent.resolve()
    template_path = dir_path / 'templates' / 'challenges.html'
    override_template('challenges.html', open(template_path).read())

def load(app):
    upgrade()
    app.db.create_all()

    register_plugin_assets_directory(app, base_path='/plugins/CTFd-PwnMyChall/assets/')
    challenges.CHALLENGE_CLASSES['pwnmychall'] = CTFdPwnMyChall

    override_challenges_template()

    app.register_blueprint(pwnmychall_pages)
    register_script("/plugins/CTFd-PwnMyChall/assets/navbar.js")

    CTFd_API_v1.add_namespace(pwnmychall_namespace, '/pwnmychall')
    
