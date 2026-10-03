"""Debounced, release-based short press; long press fires once while held."""
class Button:
    def __init__(self, long_seconds=3.0, debounce=.04):
        self.long_seconds = long_seconds
        self.debounce = debounce
        self.raw = False
        self.stable = False
        self.changed = 0
        self.started = 0
        self.armed = False  # Require a release after power-up/reconnection.
        self.fired = False

    def reset(self):
        self.armed = False
        self.fired = True

    def update(self, pressed, now):
        if pressed != self.raw:
            self.raw = pressed
            self.changed = now
        if now - self.changed < self.debounce:
            return None
        if not self.raw:
            was_pressed = self.stable
            self.stable = False
            result = 'short' if self.armed and was_pressed and not self.fired else None
            self.armed = True
            self.fired = False
            return result
        if not self.stable:
            self.stable = True
            self.started = now
        if self.armed and not self.fired and now - self.started >= self.long_seconds:
            self.fired = True
            return 'long'
        return None
