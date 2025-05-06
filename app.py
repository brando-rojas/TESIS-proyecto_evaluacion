# app.py

from flask import Flask
from config import Config
from extensions import db, login_manager
from flask_migrate import Migrate
from flask_wtf import CSRFProtect

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
migrate = Migrate(app, db)
login_manager.init_app(app)
login_manager.login_view = 'login'

csrf = CSRFProtect(app) 

from filters import *
from forms import *
from models import *
from routes import *

if __name__ == '__main__':
    app.run(debug=True)
