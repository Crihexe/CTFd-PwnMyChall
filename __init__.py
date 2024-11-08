from CTFd.plugins import challenges, register_plugin_assets_directory
from flask_restx import Namespace, Resource
from flask import session, Blueprint, abort, jsonify, redirect, url_for, request
from CTFd.models import db, Challenges, Users, Hints, ChallengeFiles, Awards, Solves, Tags, Flags, Fails
from CTFd.utils.uploads import delete_file
from logging import basicConfig, getLogger, DEBUG, ERROR
from CTFd.plugins.migrations import upgrade
from CTFd.plugins.challenges import get_chal_class
from CTFd.api import CTFd_API_v1
from CTFd.plugins.dynamic_challenges.decay import DECAY_FUNCTIONS, logarithmic, get_solve_count
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
from CTFd.utils.scores import get_user_standings


basicConfig(level=DEBUG)
logger = getLogger(__name__)

restful = Blueprint('pwnmychall', __name__)

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
        print(f"min_th {min_threshold} ch.m {challenge.min_threshold}")
        print(f"max_th {max_threshold} ch.m {challenge.max_threshold}")
        players = float(len(get_user_standings())) # per sicurezza il vero numero di player totale giocanti, lo trovo vedendo la query della classifica, siccome il db e' un po' strano e bisognerebbe capire quali Users sono player e quali no
        print(f"players: {players}")
        value = 0
        print(f"solves: {solves}")
        if solves < 1:
            value = challenge.min_reward
            print("1")
        elif 1 <= solves and solves <= max_threshold*players:
            value = challenge.max_reward
            print(min_threshold*players)
        elif solves >= min_threshold*players:
            value = challenge.min_reward
            print("3")
        elif max_threshold*players < solves and solves < min_threshold*players:
            print("calcolo con la funzione")
            z = ( (100*solves)/players - challenge.max_threshold )*( 1/(challenge.min_threshold-challenge.max_threshold) )
            z2 = z*z
            value = -1*(z2/(2*(z2-z)+1))*(challenge.max_reward-challenge.min_reward)+challenge.max_reward
            print(value)

        
        award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
        award.value = value

        if award.user_id == 1: # proviamo a vedere se il creator e' entrato
            try:
                user = Users.query.filter_by(name=challenge.creator).first()
                award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
                award.user_id = user.id
            except:
                pass
        
        db.session.commit()
        return challenge
        
    @classmethod
    def getCreatorUser(cls, challenge):
        result = Users.query.filter_by(name=challenge.creator).all()
        if len(result) > 0:
            return result[0]
        return None

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

        rewarded_user = 1   # user_id=1 perche' in teoria e' sempre l'id dell'admin della ctf, e se non c'e' l'utente quando viene creata la chall, non e' un problema cosi'. bisogna trovare un modo per assegnare il nuovo user_id onPlayerJoin
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
            "created_by_me": True,
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
        
        creator_user = Users.query.filter_by(name=creator).first()
        
        if user.id == creator_user.id:  # se chi ha creato la chall prova a risolversela, errore
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

@pwnmychall_namespace.route("/awards/bind/<chal_id>")
class Award(Resource):
    @require_verified_emails
    def get(self, chal_id): # mi dispiace :( non ne ho mezza basta che funziona
        if not authed():
            return {"success": False, "error": "User not authed."}
        
        challenge = PwnMyChall.query.filter_by(id=chal_id).first()
        try:
            user = Users.query.filter_by(name=challenge.creator).first()
            award = PwnMyChallAward.query.filter_by(challenge_id=challenge.id).first()
            award.user_id = user.id
            
            db.session.commit()

            return {"success": True, "data": {"name": user.name, "id": user.id}}
        except:
            return {"success": False, "error": "Can't bind, creator account doesn't exists yet"}

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

    CTFd_API_v1.add_namespace(pwnmychall_namespace, '/pwnmychall')
    