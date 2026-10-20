# Einstieg für Vercel: lädt die Flask-App aus muenzapp/
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'muenzapp'))
from app import app
