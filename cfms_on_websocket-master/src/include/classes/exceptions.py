class NoActiveRevisionsError(RuntimeError):
    pass


class UserError(RuntimeError): ...


class UserNotActiveError(UserError): ...


class UserTOTPRequiredError(UserError): ...


class UserTOTPFailedError(UserError): ...
