from include.classes.request import RequestHandler
from include.classes.handler import ConnectionHandler
from include.database.handler import Session
from include.database.models.classic import User


class RequestThrowExceptionHandler(RequestHandler):
    """A request handler that always throws an exception for testing purposes."""

    require_auth = True
    
    def handle(self, handler: "ConnectionHandler"):
        """Handle the request by throwing an exception."""

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None
            if "debugging" not in user.all_permissions:
                handler.conclude_request(403, {}, "User lacks debugging permission.")
                return 403, None, handler.username

        raise Exception("This is a test exception thrown by RequestThrowExceptionHandler.")