# config.py

import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'tu_clave_secreta'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
