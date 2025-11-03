# my_states.py

from state import State

# Start of our states
class Pending(State):
    """
    The state which indicates that there are limited device capabilities.
    """

    def on_event(self, event):
        if event == 'pin_entered':
            return Paid()
        else:
            return NoMoney()

        return self


class Paid(State):
    def on_event(self, event):
        if event == 'device_locked':
            return Confirmed()
        else:
            return NotDelivered()

        return self
    
class Confirmed(State):

    def on_event(self, event):
        if event == 'device_locked':
            return Final()

        return self

class NoMoney(State):
    """
    The state which indicates that there are no limitations on device
    capabilities.
    """

    def on_event(self, event):
        if event == 'device_locked':
            return Final()

        return self

class NotDelivered(State):
    """
    The state which indicates that there are no limitations on device
    capabilities.
    """

    def on_event(self, event):
        if event == 'device_locked':
            return Final()

        return self
    
class Final(State):
    """
    The state which indicates that there are no limitations on device
    capabilities.
    """

    def on_event(self, event):
        if event == 'device_locked':
            return Final()

        return self
# End of our states.
