from __future__ import unicode_literals
from __future__ import absolute_import

import fs
from os.path import join, realpath
import sys
# import pkg_resources
# import six

# Add the local code directory to the "fs" module path
from pprint import pprint
fs.__path__.append(realpath(join(__file__, "..", "..", "fs")))
