import sys
path = '/home/theastronomiefreak-byte/muenzapp'
if path not in sys.path:
    sys.path.append(path)
from app import app as application
