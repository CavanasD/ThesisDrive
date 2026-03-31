from http import HTTPStatus
from websockets import Headers, Request, Response
from websockets.sync.server import ServerConnection
from include.classes.misc.guard import LoginGuard
from include.util.address import get_client_ip


def global_process_request(
    connection: ServerConnection, request: Request
) -> Response | None:
    ip = get_client_ip(connection)

    if not LoginGuard.check_access(f"ip_limit|{ip}"):
        response_headers = Headers()
        response_headers["Content-Type"] = "text/plain"
        return Response(
            status_code=HTTPStatus.FORBIDDEN,
            reason_phrase="Forbidden",
            headers=response_headers,
            body=b"IP temporarily blocked. Too many failed attempts.",
        )

    return None
