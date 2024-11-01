from CTFd.plugins import challenges, register_plugin_assets_directory
from flask_restx import Namespace, Resource
from flask import session, Blueprint, abort, jsonify, redirect, url_for, request
from CTFd.models import db, Challenges, Users, Hints, ChallengeFiles, Awards, Solves, Tags, Flags, Fails
from CTFd.utils.uploads import delete_file
from logging import basicConfig, getLogger, DEBUG, ERROR
from CTFd.plugins.migrations import upgrade
from CTFd.plugins.challenges import get_chal_class
from CTFd.api import CTFd_API_v1
from CTFd.plugins.dynamic_challenges.decay import DECAY_FUNCTIONS, logarithmic
from CTFd.utils.user import get_current_user, authed
from pathlib import Path
from CTFd.utils.plugins import override_template
from CTFd.utils.decorators import (
    admins_only,
    during_ctf_time_only,
    require_verified_emails,
)
from CTFd.utils.decorators.visibility import (
    check_account_visibility,
    check_challenge_visibility,
    check_score_visibility,
)


basicConfig(level=DEBUG)
logger = getLogger(__name__)

restful = Blueprint('pwnmychall', __name__)

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
    reward = db.Column(db.Integer)

    def __init__(self, name, description, category, state, initial, minimum, decay, function, creator, reward, type='pwnmychall'):
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
        self.reward = reward
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
    def calculate_value(cls, challenge):
        f = DECAY_FUNCTIONS.get(challenge.function, logarithmic)
        value = f(challenge)

        challenge.value = value
        db.session.commit()
        return challenge

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
        
        db.session.commit()

        return challenge
    
    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()

        for attr, value in data.items():
            # We need to set these to floats so that the next operations don't operate on strings
            if attr in ("initial", "minimum", "decay"):
                value = float(value)
            setattr(challenge, attr, value)

        return CTFdPwnMyChall.calculate_value(challenge)

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
            "created_by_me": True,
            # forse questi due dovrebbero essere configurabili se visiibli ai player o no
            # per evitare favoritismi tra player non so
            'creator': challenge.creator,
            'reward': challenge.reward,
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
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        PwnMyChall.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()

        db.session.commit()

    @classmethod
    def attempt(cls, challenge, request):
        user = get_current_user()

        chal_class = get_chal_class(challenge.type)
        pwnmychall = challenge
        if chal_class is not PwnMyChall:
            pwnmychall = PwnMyChall.query.filter_by(id=challenge.id).first()
        
        creator = pwnmychall.creator

        if(user.name == creator):
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
        
        creator = pwnmychall.creator
        reward = pwnmychall.reward
        
        creator_user = Users.query.filter_by(name=creator).first()
        
        if user.id == creator_user.id:  # se chi ha creato la chall prova a risolversela, errore
            return
        else:
            award = Awards(user_id=creator_user.id, name=challenge.id, value=reward)
            db.session.add(award)
            
            super().solve(user, team, challenge, request)   # in teoria qui dentro fa commit

        CTFdPwnMyChall.calculate_value(challenge)

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
            if c.creator == user.name:
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
        
        return {"success": True, "data": chal.creator==user.name}


def load(app):
    upgrade()
    app.db.create_all()

    register_plugin_assets_directory(app, base_path='/plugins/CTFd-PwnMyChall/assets/')
    challenges.CHALLENGE_CLASSES['pwnmychall'] = CTFdPwnMyChall

    dir_path = Path(__file__).parent.resolve()
    template_path = dir_path / 'templates' / 'challenges.html'
    override_template('challenges.html', open(template_path).read())

    CTFd_API_v1.add_namespace(pwnmychall_namespace, '/pwnmychall')
    