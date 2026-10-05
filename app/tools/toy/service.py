import sys
from extensions.toy import service as implementation
sys.modules[__name__] = implementation
