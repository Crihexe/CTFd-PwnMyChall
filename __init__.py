from CTFd.plugins import challenges, register_plugin_assets_directory
from flask import session
from CTFd.models import db, Challenges, Hints, ChallengeFiles, Awards, Solves, Files, Tags, Teams, Flags, Fails
from CTFd import utils
from CTFd.utils.uploads import delete_file
from CTFd.utils.user import get_ip
from logging import basicConfig, getLogger, DEBUG, ERROR
from CTFd.plugins.challenges import get_chal_class

basicConfig(level=DEBUG)
logger = getLogger(__name__)

class PwnMyChall(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'pwnmychall'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    initial = db.Column(db.Integer)
    creator = db.Column(db.String(64))
    reward = db.Column(db.Integer)

    def __init__(self, name, description, value, category, creator, reward, type='pwnmychall'):
        self.name = name
        self.description = description
        self.value = value
        self.initial = value
        self.category = category
        self.type = type
        self.creator = creator
        self.reward = reward

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

    @staticmethod
    def create(request):
        challenge = PwnMyChall(
            name=request.form['name'],
            description=request.form['description'],
            value=request.form['value'],
            category=request.form['category'],
            creator=request.form['creator'],
            reward=request.form['reward'],
            type=request.form['chaltype']
        )

        if 'hidden' in request.form:
            challenge.hidden = True
        else:
            challenge.hidden = False

        db.session.add(challenge)
        db.session.commit()

        return challenge
    
    @staticmethod
    def update(challenge, request):
        challenge.name = request.form['name']
        challenge.description = request.form['description']
        challenge.value = int(request.form.get('value', 0)) if request.form.get('value', 0) else 0
        challenge.creator = request.form['creator']
        challenge.reward = int(request.form.get('reward', 0)) if request.form.get('reward', 0) else 0
        challenge.category = request.form['category']
        challenge.hidden = 'hidden' in request.form

        db.session.commit()
        db.session.close()

    @staticmethod
    def read(challenge):
        challenge = PwnMyChall.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'description': challenge.description,
            'category': challenge.category,
            'hidden': challenge.hidden,
            ##############################
            # forse questi due dovrebbero essere configurabili se visiibli ai player o no
            # per evitare favoritismi tra player non so
            'creator': challenge.creator,
            'reward': challenge.reward,
            ##############################
            'type': challenge.type,
        }

    @staticmethod
    def delete(challenge):
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

    @staticmethod
    def solve(user, team, challenge, request):
        #TODO fare qualcosa qui per rewardare anche il player che l'ha creata
        # spero di non dover modificare il db
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission,
        )
        
        db.session.add(solve)
        db.session.commit()

def load(app):
    app.db.create_all()
    register_plugin_assets_directory(app, base_path='/plugins/CTFd-PwnMyChall/assets/')
    challenges.CHALLENGE_CLASSES['pwnmychall'] = CTFdPwnMyChall
    