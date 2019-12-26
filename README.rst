fs.googledrivefs
================

.. image:: https://travis-ci.org/rkhwaja/fs.googledrivefs.svg?branch=master
    :target: https://travis-ci.org/rkhwaja/fs.googledrivefs 

.. image:: https://coveralls.io/repos/github/rkhwaja/fs.googledrivefs/badge.svg?branch=master
    :target: https://coveralls.io/github/rkhwaja/fs.googledrivefs?branch=master

Implementation of pyfilesystem2 file system for Google Drive

Usage
=====

.. code-block:: python

  fs = GoogleDriveFS(credentials=<google-auth credentials>)

  # fs is now a standard pyfilesystem2 file system

  fs2 = open_fs("googledrive:///?access_token=<oauth2 access token>&refresh_token=<oauth2 refresh token>&client_id=<oauth2 client id>&client_secret=<oauth2 client_secret>")

  # fs2 is now a standard pyfilesystem2 file system

Running tests
=============

To run the tests, set the following environment variables:

- GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH - path to a json file which will contain the credentials
- GOOGLEDRIVEFS_TEST_CLIENT_ID - your client id (see Google Developer Console)
- GOOGLEDRIVEFS_TEST_CLIENT_SECRET - your client secret (see Google Developer Console)

Then generate the credentials json file by running

.. code-block:: bash

  python generate-credentials.py

Then run the tests by executing

.. code-block:: bash

  pytest

in the root directory. The tests may take an hour or two to complete. They create and destroy many, many files and directories exclusively under the /test-googledrivefs directory in the user's Google Drive
