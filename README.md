# fs.googledrivefs

![image](https://github.com/rkhwaja/fs.googledrivefs/workflows/ci/badge.svg) [![Coverage report](https://coveralls.io/repos/github/rkhwaja/fs.googledrivefs/badge.svg?branch=master "Coverage summary")](https://coveralls.io/github/rkhwaja/fs.googledrivefs?branch=master) [![PyPI version](https://badge.fury.io/py/fs.googledrivefs.svg)](https://badge.fury.io/py/fs.googledrivefs)

Implementation of [pyfilesystem2](https://docs.pyfilesystem.org/) file system for Google Drive

# Installation

```bash
  pip install fs.googledrivefs
```

# Usage

```python
  from google.oauth2.credentials import Credentials
  from fs.googledrivefs import GoogleDriveFS

  credentials = Credentials(oauth2_access_token,
    refresh_token=oauth2_refresh_token,
    token_uri="https://www.googleapis.com/oauth2/v4/token",
    client_id=oauth2_client_id,
    client_secret=oauth2_client_secret)

  fs = GoogleDriveFS(credentials=credentials)

  # fs is now a standard pyfilesystem2 file system, alternatively you can use the opener...

  from fs.opener import open_fs

  fs2 = open_fs("googledrive:///?access_token=<oauth2 access token>&refresh_token=<oauth2 refresh token>&client_id=<oauth2 client id>&client_secret=<oauth2 client secret>")

  # fs2 is now a standard pyfilesystem2 file system
```

# Development

To run the tests, set the following environment variables:

- GOOGLEDRIVEFS_TEST_CLIENT_ID - your client id (see Google Developer Console)
- GOOGLEDRIVEFS_TEST_CLIENT_SECRET - your client secret (see Google Developer Console)
- GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH - path to a json file which will contain the credentials

Then generate the credentials json file by running

```bash
  python tests/generate-credentials.py
```

Then run the tests by executing

```bash
  pytest
```

in the root directory. The tests may take an hour or two to complete. They create and destroy many, many files and directories mostly under the /test-googledrivefs directory in the user's Google Drive and a few in the root directory
