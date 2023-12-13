from .message import Message

class Conversation:

    response_counts = 0
    
    def __init__(self, messages=None) -> None:
        self.messages = messages or []
        self.msg = Message()
        self.responses = []

    def initiate_conversation(self, system, instruction, context=None, name=None):
        self.messages, self.responses = [], []
        self.add_messages(system=system)
        self.add_messages(instruction=instruction, context=context, name=name)

    # modify the message adding to accomodate tools
    def add_messages(self, system=None, instruction=None, context=None, response=None, tool=None, name=None):
        msg = self.msg(system=system, instruction=instruction, context=context, response=response, tool=tool, name=name)
        self.messages.append(msg)

    def change_system(self, system):
        self.messages[0] = self.msg(system=system)

    def keep_last_n_exchanges(self, n: int):
        # keep last n_exchanges, one exchange is marked by one assistant response
        response_indices = [
            index for index, message in enumerate(self.messages[1:]) if message["role"] == "assistant"
        ]
        if len(response_indices) >= n:
            first_index_to_keep = response_indices[-n] + 1
            self.messages = [self.system] + self.messages[first_index_to_keep:]