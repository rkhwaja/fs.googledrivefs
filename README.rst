fs.googledrivefs
================

Implementation of pyfilesystem2 file system for Google Drive

Usage
=====

.. code-block:: python

  fs = GoogleDriveFS(
    credentials=<google-auth credentials>)

  # fs is now a standard pyfilesystem2 file system

  fs2 = open_fs("googledrive:///?access_token=<oauth2 access token>&refresh_token=<oauth2 access token>&client_id=<oauth2 client id>&client_secret=<oauth2 client_secret>")

  # fs2 is now a standard pyfilesystem2 file system
