from os.path import join, realpath

import fs

# Add the local code directory to the `fs` module path
# Can only rely on fs.__path__ being an iterable - on windows it's not a list, at least with pytest
newPath = list(fs.__path__)
newPath.insert(0, realpath(join(__file__, '..', '..', 'fs')))
fs.__path__ = newPath
