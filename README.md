# fs.googledrivefs

[![codecov](https://codecov.io/gh/rkhwaja/fs.googledrivefs/branch/master/graph/badge.svg)](https://codecov.io/gh/rkhwaja/fs.googledrivefs) [![PyPI version](https://badge.fury.io/py/fs.googledrivefs.svg)](https://badge.fury.io/py/fs.googledrivefs)

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

## Default Google Authentication

If your application is accessing the Google Drive API as a 
[GCP Service Account](https://cloud.google.com/iam/docs/service-accounts), `fs.googledrivefs` will
default to authenticating using the Service Account credentials specified by the 
[`GOOGLE_APPLICATION_CREDENTIALS` environment variable](https://cloud.google.com/docs/authentication/getting-started). 
This can greatly simplify the URLs used by the opener:

```python
  from fs.opener import open_fs

  fs2 = open_fs("googledrive:///required/path")
```

You can also use the same method of authentication when using `GoogleDriveFS` directly:

```python
  import google.auth
  from fs.googledrivefs import GoogleDriveFS

  credentials, _ = google.auth.default()
  fs = GoogleDriveFS(credentials=credentials)
```

## Using `fs.googledrivefs` with an organisation's Google Account

While access to the Google Drive API is straightforward to enable for a personal Google Account,
a user of an organisation's Google Account will typically only be able to enable an API in the
context of a
[GCP Project](https://cloud.google.com/resource-manager/docs/creating-managing-projects).
The user can then configure a 
[Service Account](https://cloud.google.com/iam/docs/understanding-service-accounts)
to access all or a sub-set of the user's files using `fs.googledrivefs` with the following steps:

- create a GCP Project
- enable the Google Drive API for that Project
- create a Service Account for that Project
- share any Drive directory (or file) with that Service Account (using the accounts email)

## Notes on forming `fs` urls for GCP Service Accounts

Say that your is drive is structured as follows:

```
/alldata
  /data1
  /data2
   :
```

Also say that you have given your application's service account access to everything in `data1`.
If your application opens url `/alldata/data1` using `fs.opener.open_fs()`, then `fs.googledrivefs`
must first get the info for `alldata` to which it has no access and so the operation fails. 

To address this we can tell `fs.googledrivefs` to treat `data1` as the root directory by supplying
the file id of `data1` as the request parameter `root_id`. The fs url you would now use is
`googledrive:///?root_id=12345678901234567890`: 

```python
  from fs.opener import open_fs

  fs2 = open_fs("googledrive:///?root_id=12345678901234567890")
```

You can also use the `rootId` when using `GoogleDriveFS` directly:

```python
  import google.auth
  from fs.googledrivefs import GoogleDriveFS

  credentials, _ = google.auth.default()
  fs = GoogleDriveFS(credentials=credentials, rootId="12345678901234567890")
```

Note that any file or directory's id is readily accessible from it's web url.

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

in the root directory
(note that if `GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH` isn't set 
then the test suite will try to use the default Google credentials).
The tests may take an hour or two to complete.
They create and destroy many, many files and directories
mostly under the /test-googledrivefs directory in the user's Google Drive
and a few in the root directory

Note that, if your tests are run using a service account,
you can set the root id using `GOOGLEDRIVEFS_TEST_ROOT_ID`.
