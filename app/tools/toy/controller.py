import sys
from extensions.toy import controller as implementation
sys.modules[__name__] = implementation
