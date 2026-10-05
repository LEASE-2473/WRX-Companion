import sys
from extensions.toy import protocol as implementation
sys.modules[__name__] = implementation
