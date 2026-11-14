"""Count explicit COM calls, including cache accessors, without retaining argument values."""


def unwrap(value):
    return value._object if isinstance(value, Counted) else value


def track(value, counter):
    if value is not None and callable(getattr(value, 'QueryInterface', None)):
        return Counted(value, counter)
    return value


class Counted:
    def __init__(self, value, counter):
        object.__setattr__(self, '_object', value)
        object.__setattr__(self, '_counter', counter)

    def __bool__(self):
        return bool(self._object)

    def __getattr__(self, name):
        try:
            value = getattr(self._object, name)
        except Exception:
            self._counter.com_calls += 1
            raise
        if callable(value):
            def call(*args, **kwargs):
                self._counter.com_calls += 1
                return track(value(*(unwrap(arg) for arg in args),
                                   **{key: unwrap(arg) for key, arg in kwargs.items()}), self._counter)
            return call
        self._counter.com_calls += 1
        return track(value, self._counter)

    def __setattr__(self, name, value):
        self._counter.com_calls += 1
        setattr(self._object, name, unwrap(value))
