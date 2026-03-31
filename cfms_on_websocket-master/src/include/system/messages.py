import gettext

t = gettext.translation("cfms_server", "include/locale", fallback=True)
_ = t.gettext


SUCCESS = _("Success")

SUBJECT_DIRECTORY_NOT_FOUND = _("Subject directory not found")

DIRECTORY_NOT_FOUND = _("Directory not found")
TARGET_OBJECT_NOT_FOUND = _("Target object not found")
TARGET_DIRECTORY_NOT_FOUND = _("Target directory not found")
TARGET_DOCUMENT_NOT_FOUND = _("Target document not found")

MISSING_USERNAME = _("Username is missing")
MISSING_USERNAME_OR_TOKEN = _("Username or token is missing")
INVALID_USER_OR_TOKEN = _("Invalid user or token")

ACCESS_DENIED = _("Access denied")
ACCESS_DENIED_MOVE_DOCUMENT = _("Access denied to move document")
ACCESS_DENIED_MOVE_DIRECTORY = _("Access denied to move directory")
ACCESS_DENIED_WRITE_DIRECTORY = _("Access denied to write directory")
PERMISSION_DENIED = _("Permission denied")

CANNOT_MOVE_DIRECTORY_INTO_SUBDIRECTORY = _(
    "Cannot move a directory into its own subdirectory"
)

NAME_DUPLICATE = _("Name duplicate")
DOCUMENT_NAME_DUPLICATE = _(
    "A document with the same name already exists in the target directory"
)
DIRECTORY_NAME_DUPLICATE = _(
    "A folder with the same name already exists in the target directory"
)
DOCUMENT_OR_DIRECTORY_NAME_DUPLICATE = _(
    "A document or folder with the same name already exists in this directory"
)
DENIED_FOR_DOC_NAME_DUPLICATE = _(
    "A document with the same name exists, and the file does not have sufficient"
    " permissions to be silently overwritten"
)
