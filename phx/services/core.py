"""Service-layer errors and the signed-in session context."""


class ServiceError(Exception):
    """A problem the user can fix; its message is shown as-is."""


class AuthError(ServiceError):
    pass


class PaymentGatewayError(ServiceError):
    pass


class Session:
    """Holds the signed-in user for the running desktop process."""

    def __init__(self):
        self.user = None

    @property
    def is_admin(self):
        return bool(self.user and self.user["role"] == "admin")

    def require_user(self):
        if not self.user:
            raise AuthError("Sign in to continue.")
        return self.user

    def require_admin(self):
        if not self.require_user()["role"] == "admin":
            raise AuthError("Only an administrator can do this.")
        return self.user

    def sold_by(self):
        user = self.require_user()
        return {"userId": user["id"], "username": user["username"], "name": user["name"]}
