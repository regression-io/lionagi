# Copyright (c) 2023 - 2024, HaiyangLi <quantocean.li at gmail dot com>
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from jinja2 import Template
from pydantic import BaseModel, Field, JsonValue, PrivateAttr

from lionagi.operatives.types import (
    ActionManager,
    FieldModel,
    FuncTool,
    Instruct,
    ModelParams,
    Operative,
    Tool,
    ToolRef,
)
from lionagi.protocols.types import (
    ID,
    MESSAGE_FIELDS,
    ActionRequest,
    ActionResponse,
    AssistantResponse,
    Communicatable,
    Element,
    IDType,
    Instruction,
    Log,
    LogManager,
    LogManagerConfig,
    Mail,
    Mailbox,
    MessageManager,
    MessageRole,
    Package,
    PackageCategory,
    Pile,
    Progression,
    Relational,
    RoledMessage,
    SenderRecipient,
    System,
)
from lionagi.service.types import iModel, iModelManager
from lionagi.settings import Settings
from lionagi.utils import UNDEFINED, alcall, copy

if TYPE_CHECKING:
    # Forward references for type checking (e.g., in operations or extended modules)
    from lionagi.session.branch import Branch

__all__ = ("Branch",)


class Branch(Element, Communicatable, Relational):
    """
    Manages a conversation 'branch' with messages, tools, and iModels.

    The `Branch` class serves as a high-level interface or orchestrator that:
        - Handles message management (`MessageManager`).
        - Registers and invokes tools/actions (`ActionManager`).
        - Manages model instances (`iModelManager`).
        - Logs activity (`LogManager`).
        - Communicates via mailboxes (`Mailbox`).

    **Key responsibilities**:
        - Storing and organizing messages, including system instructions, user instructions, and model responses.
        - Handling asynchronous or synchronous execution of LLM calls and tool invocations.
        - Providing a consistent interface for “operate,” “chat,” “communicate,” “parse,” etc.

    Attributes:
        user (SenderRecipient | None):
            The user or "owner" of this branch (often tied to a session).
        name (str | None):
            A human-readable name for this branch.
        mailbox (Mailbox):
            A mailbox for sending and receiving `Package` objects to/from other branches.

    Note:
        Actual implementations for chat, parse, operate, etc., are referenced
        via lazy loading or modular imports. You typically won't need to
        subclass `Branch`, but you can instantiate it and call the
        associated methods for complex orchestrations.
    """

    user: SenderRecipient | None = Field(
        None,
        description=(
            "The user or sender of the branch, often a session object or "
            "an external user identifier. Not to be confused with the "
            "LLM API's user parameter."
        ),
    )

    name: str | None = Field(
        None,
        description="A human-readable name of the branch (optional).",
    )

    mailbox: Mailbox = Field(
        default_factory=Mailbox,
        exclude=True,
        description="Mailbox for cross-branch or external communication.",
    )

    _message_manager: MessageManager | None = PrivateAttr(None)
    _action_manager: ActionManager | None = PrivateAttr(None)
    _imodel_manager: iModelManager | None = PrivateAttr(None)
    _log_manager: LogManager | None = PrivateAttr(None)

    def __init__(
        self,
        *,
        user: SenderRecipient = None,
        name: str | None = None,
        messages: Pile[RoledMessage] = None,  # message manager kwargs
        system: System | JsonValue = None,
        system_sender: SenderRecipient = None,
        chat_model: iModel | dict = None,  # iModelManager kwargs
        parse_model: iModel | dict = None,
        imodel: iModel = None,  # deprecated, alias of chat_model
        tools: FuncTool | list[FuncTool] = None,  # ActionManager kwargs
        log_config: LogManagerConfig | dict = None,  # LogManager kwargs
        system_datetime: bool | str = None,
        system_template: Template | str = None,
        system_template_context: dict = None,
        logs: Pile[Log] = None,
        **kwargs,
    ):
        """
        Initializes a `Branch` with references to managers and an optional mailbox.

        Args:
            user (SenderRecipient, optional):
                The user or sender context for this branch.
            name (str | None, optional):
                A human-readable name for this branch.
            messages (Pile[RoledMessage], optional):
                Initial messages for seeding the MessageManager.
            system (System | JsonValue, optional):
                Optional system-level configuration or message for the LLM.
            system_sender (SenderRecipient, optional):
                Sender to attribute to the system message if it is added.
            chat_model (iModel, optional):
                The primary "chat" iModel for conversation. If not provided,
                a default from `Settings.iModel.CHAT` is used.
            parse_model (iModel, optional):
                The "parse" iModel for structured data parsing.
                Defaults to `Settings.iModel.PARSE`.
            imodel (iModel, optional):
                Deprecated. Alias for `chat_model`.
            tools (FuncTool | list[FuncTool], optional):
                Tools or a list of tools for the ActionManager.
            log_config (LogManagerConfig | dict, optional):
                Configuration dict or object for the LogManager.
            system_datetime (bool | str, optional):
                Whether to include timestamps in system messages (True/False)
                or a string format for datetime.
            system_template (Template | str, optional):
                Optional Jinja2 template for system messages.
            system_template_context (dict, optional):
                Context for rendering the system template.
            logs (Pile[Log], optional):
                Existing logs to seed the LogManager.
            **kwargs:
                Additional parameters passed to `Element` parent init.
        """
        super().__init__(user=user, name=name, **kwargs)

        # --- MessageManager ---
        self._message_manager = MessageManager(messages=messages)
        # If system instructions or templates are provided, add them
        if any(
            i is not None
            for i in [system, system_sender, system_datetime, system_template]
        ):

            self._message_manager.add_message(
                system=system,
                system_datetime=system_datetime,
                template=system_template,
                template_context=system_template_context,
                recipient=self.id,
                sender=system_sender or self.user or MessageRole.SYSTEM,
            )

        chat_model = chat_model or imodel
        if not chat_model:
            chat_model = iModel(**Settings.iModel.CHAT)
        if not parse_model:
            parse_model = iModel(**Settings.iModel.PARSE)

        if isinstance(chat_model, dict):
            chat_model = iModel.from_dict(chat_model)
        if isinstance(parse_model, dict):
            parse_model = iModel.from_dict(parse_model)

        self._imodel_manager = iModelManager(
            chat=chat_model, parse=parse_model
        )

        # --- ActionManager ---
        self._action_manager = ActionManager(tools)

        # --- LogManager ---
        if log_config:
            if isinstance(log_config, dict):
                log_config = LogManagerConfig(**log_config)
            self._log_manager = LogManager.from_config(log_config, logs=logs)
        else:
            self._log_manager = LogManager(**Settings.Config.LOG, logs=logs)

    # -------------------------------------------------------------------------
    # Properties to expose managers and core data
    # -------------------------------------------------------------------------
    @property
    def system(self) -> System | None:
        """The system message/configuration, if any."""
        return self._message_manager.system

    @property
    def msgs(self) -> MessageManager:
        """Returns the associated MessageManager."""
        return self._message_manager

    @property
    def acts(self) -> ActionManager:
        """Returns the associated ActionManager for tool management."""
        return self._action_manager

    @property
    def mdls(self) -> iModelManager:
        """Returns the associated iModelManager."""
        return self._imodel_manager

    @property
    def messages(self) -> Pile[RoledMessage]:
        """Convenience property to retrieve all messages from MessageManager."""
        return self._message_manager.messages

    @property
    def logs(self) -> Pile[Log]:
        """Convenience property to retrieve all logs from the LogManager."""
        return self._log_manager.logs

    @property
    def chat_model(self) -> iModel:
        """
        The primary "chat" model (`iModel`) used for conversational LLM calls.
        """
        return self._imodel_manager.chat

    @chat_model.setter
    def chat_model(self, value: iModel) -> None:
        """
        Sets the primary "chat" model in the iModelManager.

        Args:
            value (iModel): The new chat model to register.
        """
        self._imodel_manager.register_imodel("chat", value)

    @property
    def parse_model(self) -> iModel:
        """The "parse" model (`iModel`) used for structured data parsing."""
        return self._imodel_manager.parse

    @parse_model.setter
    def parse_model(self, value: iModel) -> None:
        """
        Sets the "parse" model in the iModelManager.

        Args:
            value (iModel): The new parse model to register.
        """
        self._imodel_manager.register_imodel("parse", value)

    @property
    def tools(self) -> dict[str, Tool]:
        """
        All registered tools (actions) in the ActionManager,
        keyed by their tool names or IDs.
        """
        return self._action_manager.registry

    # -------------------------------------------------------------------------
    # Cloning
    # -------------------------------------------------------------------------
    async def aclone(self, sender: ID.Ref = None) -> "Branch":
        """
        Asynchronously clones this `Branch` with optional new sender ID.

        Args:
            sender (ID.Ref, optional):
                If provided, this ID is set as the sender for all cloned messages.

        Returns:
            Branch: A new branch instance, containing cloned state.
        """
        async with self.msgs.messages:
            return self.clone(sender)

    def clone(self, sender: ID.Ref = None) -> "Branch":
        """
        Clones this `Branch` synchronously, optionally updating the sender ID.

        Args:
            sender (ID.Ref, optional):
                If provided, all messages in the clone will have this sender ID.
                Otherwise, uses the current branch's ID.

        Raises:
            ValueError: If `sender` is not a valid ID.Ref.

        Returns:
            Branch: A new branch object with a copy of the messages, system info, etc.
        """
        if sender is not None:
            if not ID.is_id(sender):
                raise ValueError(
                    f"Cannot clone Branch: '{sender}' is not a valid sender ID."
                )
            sender = ID.get_id(sender)

        system = self.msgs.system.clone() if self.msgs.system else None
        tools = (
            list(self._action_manager.registry.values())
            if self._action_manager.registry
            else None
        )
        branch_clone = Branch(
            system=system,
            user=self.user,
            messages=[msg.clone() for msg in self.msgs.messages],
            tools=tools,
            metadata={"clone_from": self},
        )
        for message in branch_clone.msgs.messages:
            message.sender = sender or self.id
            message.recipient = branch_clone.id

        return branch_clone

    # -------------------------------------------------------------------------
    # Conversion / Serialization
    # -------------------------------------------------------------------------
    def to_df(self, *, progression: Progression = None) -> pd.DataFrame:
        """
        Convert branch messages into a `pandas.DataFrame`.

        Args:
            progression (Progression, optional):
                A custom message ordering. If `None`, uses the stored progression.

        Returns:
            pd.DataFrame: Each row represents a message, with columns defined by MESSAGE_FIELDS.
        """
        if progression is None:
            progression = self.msgs.progression

        msgs = [
            self.msgs.messages[i]
            for i in progression
            if i in self.msgs.messages
        ]
        p = Pile(collections=msgs)
        return p.to_df(columns=MESSAGE_FIELDS)

    # -------------------------------------------------------------------------
    # Mailbox Send / Receive
    # -------------------------------------------------------------------------
    def send(
        self,
        recipient: IDType,
        category: PackageCategory | None,
        item: Any,
        request_source: IDType | None = None,
    ) -> None:
        """
        Sends a `Package` (wrapped in a `Mail` object) to a specified recipient.

        Args:
            recipient (IDType):
                ID of the recipient branch or component.
            category (PackageCategory | None):
                The category/type of the package (e.g., 'message', 'tool', 'imodel').
            item (Any):
                The payload to send (e.g., a message, tool reference, model, etc.).
            request_source (IDType | None):
                The ID that prompted or requested this send operation (optional).
        """
        package = Package(
            category=category,
            item=item,
            request_source=request_source,
        )

        mail = Mail(
            sender=self.id,
            recipient=recipient,
            package=package,
        )
        self.mailbox.append_out(mail)

    def receive(
        self,
        sender: IDType,
        message: bool = False,
        tool: bool = False,
        imodel: bool = False,
    ) -> None:
        """
        Retrieves and processes mail from a given sender according to the specified flags.

        Args:
            sender (IDType):
                The ID of the mail sender.
            message (bool):
                If `True`, process packages categorized as "message".
            tool (bool):
                If `True`, process packages categorized as "tool".
            imodel (bool):
                If `True`, process packages categorized as "imodel".

        Raises:
            ValueError: If no mail exists from the specified sender,
                        or if a package is invalid for the chosen category.
        """
        sender = ID.get_id(sender)
        if sender not in self.mailbox.pending_ins.keys():
            raise ValueError(f"No mail or package found from sender: {sender}")

        skipped_requests = Progression()
        while self.mailbox.pending_ins[sender]:
            mail_id = self.mailbox.pending_ins[sender].popleft()
            mail: Mail = self.mailbox.pile_[mail_id]

            if mail.category == "message" and message:
                if not isinstance(mail.package.item, RoledMessage):
                    raise ValueError(
                        "Invalid message package: The item must be a `RoledMessage`."
                    )
                new_message = mail.package.item.clone()
                new_message.sender = mail.sender
                new_message.recipient = self.id
                self.msgs.messages.include(new_message)
                self.mailbox.pile_.pop(mail_id)

            elif mail.category == "tool" and tool:
                if not isinstance(mail.package.item, Tool):
                    raise ValueError(
                        "Invalid tool package: The item must be a `Tool` instance."
                    )
                self._action_manager.register_tools(mail.package.item)
                self.mailbox.pile_.pop(mail_id)

            elif mail.category == "imodel" and imodel:
                if not isinstance(mail.package.item, iModel):
                    raise ValueError(
                        "Invalid iModel package: The item must be an `iModel` instance."
                    )
                self._imodel_manager.register_imodel(
                    mail.package.item.name or "chat", mail.package.item
                )
                self.mailbox.pile_.pop(mail_id)

            else:
                # If the category doesn't match the flags or is unhandled
                skipped_requests.append(mail)

        # Requeue any skipped mail
        self.mailbox.pending_ins[sender] = skipped_requests
        if len(self.mailbox.pending_ins[sender]) == 0:
            self.mailbox.pending_ins.pop(sender)

    async def asend(
        self,
        recipient: IDType,
        category: PackageCategory | None,
        package: Any,
        request_source: IDType | None = None,
    ):
        """
        Async version of `send()`.

        Args:
            recipient (IDType):
                ID of the recipient branch or component.
            category (PackageCategory | None):
                The category/type of the package.
            package (Any):
                The item(s) to send (message/tool/model).
            request_source (IDType | None):
                The origin request ID (if any).
        """
        async with self.mailbox.pile_:
            self.send(recipient, category, package, request_source)

    async def areceive(
        self,
        sender: IDType,
        message: bool = False,
        tool: bool = False,
        imodel: bool = False,
    ) -> None:
        """
        Async version of `receive()`.

        Args:
            sender (IDType):
                The ID of the mail sender.
            message (bool):
                If `True`, process packages categorized as "message".
            tool (bool):
                If `True`, process packages categorized as "tool".
            imodel (bool):
                If `True`, process packages categorized as "imodel".
        """
        async with self.mailbox.pile_:
            self.receive(sender, message, tool, imodel)

    def receive_all(self) -> None:
        """
        Receives mail from all known senders without filtering.

        (Duplicate method included in your snippet; you may unify or remove.)
        """
        for key in self.mailbox.pending_ins:
            self.receive(key)

    # -------------------------------------------------------------------------
    # Dictionary Conversion
    # -------------------------------------------------------------------------
    def to_dict(self):
        """
        Serializes the branch to a Python dictionary, including:
            - Messages
            - Logs
            - Chat/Parse models
            - System message
            - LogManager config
            - Metadata

        Returns:
            dict: A dictionary representing the branch's internal state.
        """
        meta = {}
        if "clone_from" in self.metadata:

            # Provide some reference info about the source from which we cloned
            meta["clone_from"] = {
                "id": str(self.metadata["clone_from"].id),
                "user": str(self.metadata["clone_from"].user),
                "created_at": self.metadata["clone_from"].created_at,
                "progression": [
                    str(i)
                    for i in self.metadata["clone_from"].msgs.progression
                ],
            }
        meta.update(
            copy({k: v for k, v in self.metadata.items() if k != "clone_from"})
        )

        dict_ = super().to_dict()
        dict_["messages"] = self.messages.to_dict()
        dict_["logs"] = self.logs.to_dict()
        dict_["chat_model"] = self.chat_model.to_dict()
        dict_["parse_model"] = self.parse_model.to_dict()
        if self.system:
            dict_["system"] = self.system.to_dict()
        dict_["log_config"] = self._log_manager._config.model_dump()
        dict_["metadata"] = meta
        return dict_

    @classmethod
    def from_dict(cls, data: dict):
        """
        Creates a `Branch` instance from a serialized dictionary.

        Args:
            data (dict):
                Must include (or optionally include) `messages`, `logs`,
                `chat_model`, `parse_model`, `system`, and `log_config`.

        Returns:
            Branch: A new `Branch` instance based on the deserialized data.
        """
        dict_ = {
            "messages": data.pop("messages", UNDEFINED),
            "logs": data.pop("logs", UNDEFINED),
            "chat_model": data.pop("chat_model", UNDEFINED),
            "parse_model": data.pop("parse_model", UNDEFINED),
            "system": data.pop("system", UNDEFINED),
            "log_config": data.pop("log_config", UNDEFINED),
        }
        params = {}

        # Merge in the rest of the data
        for k, v in data.items():
            # If the item is a dict with an 'id', we expand it
            if isinstance(v, dict) and "id" in v:
                params.update(v)
            else:
                params[k] = v

        params.update(dict_)
        # Remove placeholders (UNDEFINED) so we don't incorrectly assign them
        return cls(**{k: v for k, v in params.items() if v is not UNDEFINED})

    def dump_logs(self, clear: bool = True, persist_path=None):
        """
        Dumps the log to a file or clears it.

        Args:
            clear (bool, optional):
                If `True`, clears the log after dumping.
            persist_path (str, optional):
                The file path to save the log to.
        """
        self._log_manager.dump(clear=clear, persist_path=persist_path)

    async def adump_logs(self, clear: bool = True, persist_path=None):
        """
        Asynchronously dumps the log to a file or clears it.
        """
        await self._log_manager.adump(clear=clear, persist_path=persist_path)

    # -------------------------------------------------------------------------
    # Asynchronous Operations (chat, parse, operate, etc.)
    # -------------------------------------------------------------------------
    async def chat(
        self,
        instruction: Instruction | JsonValue = None,
        guidance: JsonValue = None,
        context: JsonValue = None,
        sender: ID.Ref = None,
        recipient: ID.Ref = None,
        request_fields: list[str] | dict[str, JsonValue] = None,
        response_format: type[BaseModel] | BaseModel = None,
        progression: Progression | list[ID[RoledMessage].ID] = None,
        imodel: iModel = None,
        tool_schemas: list[dict] = None,
        images: list = None,
        image_detail: Literal["low", "high", "auto"] = None,
        plain_content: str = None,
        return_ins_res_message: bool = False,
        **kwargs,
    ) -> tuple[Instruction, AssistantResponse]:
        """
        Invokes the chat model with the current conversation history. This method does not
        automatically add messages to the branch. It is typically used for orchestrating.

        **High-level flow**:
            1. Construct a sequence of messages from the stored progression.
            2. Integrate any pending action responses into the context.
            3. Invoke the chat model with the combined messages.
            4. Capture and return the final response as an `AssistantResponse`.

        Args:
            instruction (Any):
                Main user instruction text or structured data.
            guidance (Any):
                Additional system or user guidance text.
            context (Any):
                Context data to pass to the model.
            sender (Any):
                The user or entity sending this message (defaults to `Branch.user`).
            recipient (Any):
                The recipient of this message (defaults to `self.id`).
            request_fields (Any):
                Partial field-level validation reference (rarely used).
            response_format (type[BaseModel], optional):
                A Pydantic model type for structured model responses.
            progression (Any):
                Custom ordering of messages in the conversation.
            imodel (iModel, optional):
                An override for the chat model to use. If not provided, uses `self.chat_model`.
            tool_schemas (Any, optional):
                Additional schemas for tool invocation in function-calling.
            images (list, optional):
                Optional images relevant to the model's context.
            image_detail (Literal["low", "high", "auto"], optional):
                Level of detail for image-based context (if relevant).
            plain_content (str, optional):
                Plain text content, will override any other content.
            return_ins_res_message:
                If `True`, returns the final `Instruction` and `AssistantResponse` objects.
                else, returns only the response content.
            **kwargs:
                Additional parameters for the LLM invocation.

        Returns:
            tuple[Instruction, AssistantResponse]:
                The `Instruction` object and the final `AssistantResponse`.
        """
        from lionagi.operations.chat.chat import chat

        return await chat(
            self,
            instruction=instruction,
            guidance=guidance,
            context=context,
            sender=sender,
            recipient=recipient,
            request_fields=request_fields,
            response_format=response_format,
            progression=progression,
            chat_model=imodel,
            tool_schemas=tool_schemas,
            images=images,
            image_detail=image_detail,
            plain_content=plain_content,
            return_ins_res_message=return_ins_res_message,
            **kwargs,
        )

    async def parse(
        self,
        text: str,
        handle_validation: Literal[
            "raise", "return_value", "return_none"
        ] = "return_value",
        max_retries: int = 3,
        request_type: type[BaseModel] = None,
        operative: Operative = None,
        similarity_algo="jaro_winkler",
        similarity_threshold: float = 0.85,
        fuzzy_match: bool = True,
        handle_unmatched: Literal[
            "ignore", "raise", "remove", "fill", "force"
        ] = "force",
        fill_value: Any = None,
        fill_mapping: dict[str, Any] | None = None,
        strict: bool = False,
        suppress_conversion_errors: bool = False,
        response_format: type[BaseModel] = None,
    ):
        """
        Attempts to parse text into a structured Pydantic model using parse model logic. New messages are not appeneded to conversation context.

        If fuzzy matching is enabled, tries to map partial or uncertain keys
        to the known fields of the model. Retries are performed if initial parsing fails.

        Args:
            text (str):
                The raw text to parse.
            handle_validation (Literal["raise","return_value","return_none"]):
                What to do if parsing fails (default: "return_value").
            max_retries (int):
                Number of times to retry parsing on failure (default: 3).
            request_type (type[BaseModel], optional):
                The Pydantic model to parse into.
            operative (Operative, optional):
                An `Operative` object with known request model and settings.
            similarity_algo (str):
                Algorithm name for fuzzy field matching.
            similarity_threshold (float):
                Threshold for matching (0.0 - 1.0).
            fuzzy_match (bool):
                Whether to attempt fuzzy matching for unmatched fields.
            handle_unmatched (Literal["ignore","raise","remove","fill","force"]):
                Policy for unrecognized fields (default: "force").
            fill_value (Any):
                Default placeholder for missing fields (if fill is used).
            fill_mapping (dict[str, Any] | None):
                A mapping of specific fields to fill values.
            strict (bool):
                If True, raises errors on ambiguous fields or data types.
            suppress_conversion_errors (bool):
                If True, logs or ignores conversion errors instead of raising.

        Returns:
            BaseModel | dict | str | None:
                Parsed model instance, or a fallback based on `handle_validation`.
        """
        from lionagi.operations.parse.parse import parse

        return await parse(
            self,
            text=text,
            handle_validation=handle_validation,
            max_retries=max_retries,
            request_type=request_type,
            operative=operative,
            similarity_algo=similarity_algo,
            similarity_threshold=similarity_threshold,
            fuzzy_match=fuzzy_match,
            handle_unmatched=handle_unmatched,
            fill_value=fill_value,
            fill_mapping=fill_mapping,
            strict=strict,
            suppress_conversion_errors=suppress_conversion_errors,
            response_format=response_format,
        )

    async def operate(
        self,
        *,
        instruct: Instruct = None,
        instruction: Instruction | JsonValue = None,
        guidance: JsonValue = None,
        context: JsonValue = None,
        sender: SenderRecipient = None,
        recipient: SenderRecipient = None,
        progression: Progression = None,
        imodel: iModel = None,  # deprecated, alias of chat_model
        chat_model: iModel = None,
        invoke_actions: bool = True,
        tool_schemas: list[dict] = None,
        images: list = None,
        image_detail: Literal["low", "high", "auto"] = None,
        parse_model: iModel = None,
        skip_validation: bool = False,
        tools: ToolRef = None,
        operative: Operative = None,
        response_format: type[
            BaseModel
        ] = None,  # alias of operative.request_type
        return_operative: bool = False,
        actions: bool = False,
        reason: bool = False,
        action_kwargs: dict = None,
        field_models: list[FieldModel] = None,
        exclude_fields: list | dict | None = None,
        request_params: ModelParams = None,
        request_param_kwargs: dict = None,
        response_params: ModelParams = None,
        response_param_kwargs: dict = None,
        handle_validation: Literal[
            "raise", "return_value", "return_none"
        ] = "return_value",
        operative_model: type[BaseModel] = None,
        request_model: type[BaseModel] = None,
        **kwargs,
    ) -> list | BaseModel | None | dict | str:
        """
        Orchestrates an "operate" flow with optional tool invocation and
        structured response validation. Messages **are** automatically
        added to the conversation.

        **Workflow**:
        1) Builds or updates an `Operative` object to specify how the LLM should respond.
        2) Sends an instruction (`instruct`) or direct `instruction` text to `branch.chat()`.
        3) Optionally validates/parses the result into a model or dictionary.
        4) If `invoke_actions=True`, any requested tool calls are automatically invoked.
        5) Returns either the final structure, raw response, or an updated `Operative`.

        Args:
            branch (Branch):
                The active branch that orchestrates messages, models, and logs.
            instruct (Instruct, optional):
                Contains the instruction, guidance, context, etc. If not provided,
                uses `instruction`, `guidance`, `context` directly.
            instruction (Instruction | JsonValue, optional):
                The main user instruction or content for the LLM.
            guidance (JsonValue, optional):
                Additional system or user instructions.
            context (JsonValue, optional):
                Extra context data.
            sender (SenderRecipient, optional):
                The sender ID for newly added messages.
            recipient (SenderRecipient, optional):
                The recipient ID for newly added messages.
            progression (Progression, optional):
                Custom ordering of conversation messages.
            imodel (iModel, deprecated):
                Alias of `chat_model`.
            chat_model (iModel, optional):
                The LLM used for the main chat operation. Defaults to `branch.chat_model`.
            invoke_actions (bool, optional):
                If `True`, executes any requested tools found in the LLM's response.
            tool_schemas (list[dict], optional):
                Additional schema definitions for tool-based function-calling.
            images (list, optional):
                Optional images appended to the LLM context.
            image_detail (Literal["low","high","auto"], optional):
                The level of image detail, if relevant.
            parse_model (iModel, optional):
                Model used for deeper or specialized parsing, if needed.
            skip_validation (bool, optional):
                If `True`, bypasses final validation and returns raw text or partial structure.
            tools (ToolRef, optional):
                Tools to be registered or made available if `invoke_actions` is True.
            operative (Operative, optional):
                If provided, reuses an existing operative's config for parsing/validation.
            response_format (type[BaseModel], optional):
                Expected Pydantic model for the final response (alias for `operative.request_type`).
            return_operative (bool, optional):
                If `True`, returns the entire `Operative` object after processing
                rather than the structured or raw output.
            actions (bool, optional):
                If `True`, signals that function-calling or "action" usage is expected.
            reason (bool, optional):
                If `True`, signals that the LLM should provide chain-of-thought or reasoning (where applicable).
            action_kwargs (dict | None, optional):
                Additional parameters for the `branch.act()` call if tools are invoked.
            field_models (list[FieldModel] | None, optional):
                Field-level definitions or overrides for the model schema.
            exclude_fields (list|dict|None, optional):
                Which fields to exclude from final validation or model building.
            request_params (ModelParams | None, optional):
                Extra config for building the request model in the operative.
            request_param_kwargs (dict|None, optional):
                Additional kwargs passed to the `ModelParams` constructor for the request.
            response_params (ModelParams | None, optional):
                Config for building the response model after actions.
            response_param_kwargs (dict|None, optional):
                Additional kwargs passed to the `ModelParams` constructor for the response.
            handle_validation (Literal["raise","return_value","return_none"], optional):
                How to handle parsing failures (default: "return_value").
            operative_model (type[BaseModel], deprecated):
                Alias for `response_format`.
            request_model (type[BaseModel], optional):
                Another alias for `response_format`.
            **kwargs:
                Additional keyword arguments passed to the LLM via `branch.chat()`.

        Returns:
            list | BaseModel | None | dict | str:
                - The parsed or raw response from the LLM,
                - `None` if validation fails and `handle_validation='return_none'`,
                - or the entire `Operative` object if `return_operative=True`.

        Raises:
            ValueError:
                - If both `operative_model` and `response_format` or `request_model` are given.
                - If the LLM's response cannot be parsed into the expected format and `handle_validation='raise'`.
        """
        from lionagi.operations.operate.operate import operate

        return await operate(
            self,
            instruct=instruct,
            instruction=instruction,
            guidance=guidance,
            context=context,
            sender=sender,
            recipient=recipient,
            progression=progression,
            chat_model=chat_model,
            invoke_actions=invoke_actions,
            tool_schemas=tool_schemas,
            images=images,
            image_detail=image_detail,
            parse_model=parse_model,
            skip_validation=skip_validation,
            tools=tools,
            operative=operative,
            response_format=response_format,
            return_operative=return_operative,
            actions=actions,
            reason=reason,
            action_kwargs=action_kwargs,
            field_models=field_models,
            exclude_fields=exclude_fields,
            request_params=request_params,
            request_param_kwargs=request_param_kwargs,
            response_params=response_params,
            response_param_kwargs=response_param_kwargs,
            handle_validation=handle_validation,
            operative_model=operative_model,
            request_model=request_model,
            imodel=imodel,
            **kwargs,
        )

    async def communicate(
        self,
        instruction: Instruction | JsonValue = None,
        *,
        guidance: JsonValue = None,
        context: JsonValue = None,
        plain_content: str = None,
        sender: SenderRecipient = None,
        recipient: SenderRecipient = None,
        progression: ID.IDSeq = None,
        request_model: type[BaseModel] | BaseModel | None = None,
        response_format: type[BaseModel] = None,
        request_fields: dict | list[str] = None,
        imodel: iModel = None,  # alias of chat_model
        chat_model: iModel = None,
        parse_model: iModel = None,
        skip_validation: bool = False,
        images: list = None,
        image_detail: Literal["low", "high", "auto"] = None,
        num_parse_retries: int = 3,
        fuzzy_match_kwargs: dict = None,
        clear_messages: bool = False,
        operative_model: type[BaseModel] = None,
        **kwargs,
    ):
        """
        A simpler orchestration than `operate()`, typically without tool invocation. Messages are automatically added to the conversation.

        **Flow**:
          1. Sends an instruction (or conversation) to the chat model.
          2. Optionally parses the response into a structured model or fields.
          3. Returns either the raw string, the parsed model, or a dict of fields.

        Args:
            instruction (Instruction | dict, optional):
                The user's main query or data.
            guidance (JsonValue, optional):
                Additional instructions or context for the LLM.
            context (JsonValue, optional):
                Extra data or context.
            plain_content (str, optional):
                Plain text content appended to the instruction.
            sender (SenderRecipient, optional):
                Sender ID (defaults to `Branch.user`).
            recipient (SenderRecipient, optional):
                Recipient ID (defaults to `self.id`).
            progression (ID.IDSeq, optional):
                Custom ordering of messages.
            request_model (type[BaseModel] | BaseModel | None, optional):
                Model for validating or structuring the LLM's response.
            response_format (type[BaseModel], optional):
                Alias for `request_model`. If both are provided, raises ValueError.
            request_fields (dict|list[str], optional):
                If you only need certain fields from the LLM's response.
            imodel (iModel, optional):
                Deprecated alias for `chat_model`.
            chat_model (iModel, optional):
                An alternative to the default chat model.
            parse_model (iModel, optional):
                If parsing is needed, you can override the default parse model.
            skip_validation (bool, optional):
                If True, returns the raw response string unvalidated.
            images (list, optional):
                Any relevant images.
            image_detail (Literal["low","high","auto"], optional):
                Image detail level (if used).
            num_parse_retries (int, optional):
                Maximum parsing retries (capped at 5).
            fuzzy_match_kwargs (dict, optional):
                Additional settings for fuzzy field matching (if used).
            clear_messages (bool, optional):
                Whether to clear stored messages before sending.
            operative_model (type[BaseModel], optional):
                Deprecated, alias for `response_format`.
            **kwargs:
                Additional arguments for the underlying LLM call.

        Returns:
            Any:
                - Raw string (if `skip_validation=True`),
                - A validated Pydantic model,
                - A dict of the requested fields,
                - or `None` if parsing fails and `handle_validation='return_none'`.
        """
        from lionagi.operations.communicate.communicate import communicate

        return await communicate(
            self,
            instruction=instruction,
            guidance=guidance,
            context=context,
            plain_content=plain_content,
            sender=sender,
            recipient=recipient,
            progression=progression,
            request_model=request_model,
            response_format=response_format,
            request_fields=request_fields,
            chat_model=chat_model or imodel,
            parse_model=parse_model,
            skip_validation=skip_validation,
            images=images,
            image_detail=image_detail,
            num_parse_retries=num_parse_retries,
            fuzzy_match_kwargs=fuzzy_match_kwargs,
            clear_messages=clear_messages,
            operative_model=operative_model,
            **kwargs,
        )

    async def _act(
        self,
        action_request: ActionRequest | BaseModel | dict,
        suppress_errors: bool = False,
    ) -> ActionResponse:
        """
        Internal method to invoke a tool (action) asynchronously.

        Args:
            action_request (ActionRequest|BaseModel|dict):
                Must contain `function` and `arguments`.
            suppress_errors (bool, optional):
                If True, errors are logged instead of raised.

        Returns:
            ActionResponse: Result of the tool invocation or `None` if suppressed.
        """
        from lionagi.operations._act.act import _act

        return await _act(self, action_request, suppress_errors)

    async def act(
        self,
        action_request: list | ActionRequest | BaseModel | dict,
        *,
        suppress_errors: bool = True,
        sanitize_input: bool = False,
        unique_input: bool = False,
        num_retries: int = 0,
        initial_delay: float = 0,
        retry_delay: float = 0,
        backoff_factor: float = 1,
        retry_default: Any = UNDEFINED,
        retry_timeout: float | None = None,
        retry_timing: bool = False,
        max_concurrent: int | None = None,
        throttle_period: float | None = None,
        flatten: bool = True,
        dropna: bool = True,
        unique_output: bool = False,
        flatten_tuple_set: bool = False,
    ) -> list[ActionResponse] | ActionResponse | Any:
        """
        Public, potentially batched, asynchronous interface to run one or multiple action requests.

        Args:
            action_request (list|ActionRequest|BaseModel|dict):
                A single or list of action requests, each requiring
                `function` and `arguments`.
            suppress_errors (bool):
                If True, log errors instead of raising exceptions.
            sanitize_input (bool):
                Reserved. Potentially sanitize the action arguments.
            unique_input (bool):
                Reserved. Filter out duplicate requests.
            num_retries (int):
                Number of times to retry on failure (default 0).
            initial_delay (float):
                Delay before first attempt (seconds).
            retry_delay (float):
                Base delay between retries.
            backoff_factor (float):
                Multiplier for the `retry_delay` after each attempt.
            retry_default (Any):
                Fallback value if all retries fail (if suppressing errors).
            retry_timeout (float|None):
                Overall timeout for all attempts (None = no limit).
            retry_timing (bool):
                If True, track time used for retries.
            max_concurrent (int|None):
                Maximum concurrent tasks (if batching).
            throttle_period (float|None):
                Minimum spacing (in seconds) between requests.
            flatten (bool):
                If a list of results is returned, flatten them if possible.
            dropna (bool):
                Remove `None` or invalid results from final output if True.
            unique_output (bool):
                Only return unique results if True.
            flatten_tuple_set (bool):
                Flatten nested tuples in results if True.

        Returns:
            Any:
                The result or results from the invoked tool(s).
        """
        params = locals()
        params.pop("self")
        params.pop("action_request")
        return await alcall(action_request, self._act, **params)

    async def translate(
        self,
        text: str,
        technique: Literal["SynthLang"] = "SynthLang",
        technique_kwargs: dict = None,
        compress: bool = False,
        chat_model: iModel = None,
        compress_model: iModel = None,
        compression_ratio: float = 0.2,
        compress_kwargs=None,
        verbose: bool = True,
        new_branch: bool = True,
        **kwargs,
    ) -> str:
        """
        An example "translate" operation that transforms text using a chosen technique
        (e.g., "SynthLang"). Optionally compresses text with a custom `compress_model`.

        Args:
            text (str):
                The text to be translated or transformed.
            technique (Literal["SynthLang"]):
                The translation/transform technique (currently only "SynthLang").
            technique_kwargs (dict, optional):
                Additional parameters for the chosen technique.
            compress (bool):
                Whether to compress the resulting text further.
            chat_model (iModel, optional):
                A custom model for the translation step (defaults to self.chat_model).
            compress_model (iModel, optional):
                A separate model for compression (if `compress=True`).
            compression_ratio (float):
                Desired compression ratio if compressing text (0.0 - 1.0).
            compress_kwargs (dict, optional):
                Additional arguments for the compression step.
            verbose (bool):
                If True, prints debug/logging info.
            new_branch (bool):
                If True, performs the translation in a new branch context.
            **kwargs:
                Additional parameters passed through to the technique function.

        Returns:
            str: The transformed (and optionally compressed) text.
        """
        from lionagi.operations.translate.translate import translate

        return await translate(
            branch=self,
            text=text,
            technique=technique,
            technique_kwargs=technique_kwargs,
            compress=compress,
            chat_model=chat_model,
            compress_model=compress_model,
            compression_ratio=compression_ratio,
            compress_kwargs=compress_kwargs,
            verbose=verbose,
            new_branch=new_branch,
            **kwargs,
        )

    async def select(
        self,
        instruct: Instruct | dict[str, Any],
        choices: list[str] | type[Enum] | dict[str, Any],
        max_num_selections: int = 1,
        branch_kwargs: dict[str, Any] | None = None,
        verbose: bool = False,
        **kwargs: Any,
    ):
        """
        Performs a selection operation from given choices using an LLM-driven approach.

        Args:
            instruct (Instruct|dict[str, Any]):
                The instruction model or dictionary for the LLM call.
            choices (list[str]|type[Enum]|dict[str,Any]):
                The set of options to choose from.
            max_num_selections (int):
                Maximum allowed selections (default = 1).
            branch_kwargs (dict[str, Any]|None):
                Extra arguments to create or configure a new branch if needed.
            verbose (bool):
                If True, prints debug info.
            **kwargs:
                Additional arguments for the underlying `operate()` call.

        Returns:
            Any:
                A `SelectionModel` or similar that indicates the user's choice(s).
        """
        from lionagi.operations.select.select import select

        return await select(
            branch=self,
            instruct=instruct,
            choices=choices,
            max_num_selections=max_num_selections,
            branch_kwargs=branch_kwargs,
            verbose=verbose,
            **kwargs,
        )

    async def compress(
        self,
        text: str,
        system_msg: str = None,
        target_ratio: float = 0.2,
        n_samples: int = 5,
        max_tokens_per_sample=80,
        verbose=True,
    ) -> str:
        """
        Uses the `chat_model`'s built-in compression routine to shorten text.

        Args:
            text (str):
                The text to compress.
            system_msg (str, optional):
                System-level instructions, appended to the prompt.
            target_ratio (float):
                Desired compression ratio (0.0-1.0).
            n_samples (int):
                How many compression attempts to combine or evaluate.
            max_tokens_per_sample (int):
                Max token count per sample chunk.
            verbose (bool):
                If True, logs or prints progress.

        Returns:
            str: The compressed text.
        """
        return await self.chat_model.compress_text(
            text=text,
            system_msg=system_msg,
            target_ratio=target_ratio,
            n_samples=n_samples,
            max_tokens_per_sample=max_tokens_per_sample,
            verbose=verbose,
        )

    async def interpret(
        self,
        text: str,
        domain: str | None = None,
        style: str | None = None,
        **kwargs,
    ) -> str:
        """
        Interprets (rewrites) a user's raw input into a more formal or structured
        LLM prompt. This function can be seen as a "prompt translator," which
        ensures the user's original query is clarified or enhanced for better
        LLM responses. Messages are not automatically added to the conversation.

        The method calls `branch.chat()` behind the scenes with a system prompt
        that instructs the LLM to rewrite the input. You can provide additional
        parameters in `**kwargs` (e.g., `parse_model`, `skip_validation`, etc.)
        if you want to shape how the rewriting is done.

        Args:
            branch (Branch):
                The active branch context for messages, logging, etc.
            text (str):
                The raw user input or question that needs interpreting.
            domain (str | None, optional):
                Optional domain hint (e.g. "finance", "marketing", "devops").
                The LLM can use this hint to tailor its rewriting approach.
            style (str | None, optional):
                Optional style hint (e.g. "concise", "detailed").
            **kwargs:
                Additional arguments passed to `branch.communicate()`,
                such as `parse_model`, `skip_validation`, `temperature`, etc.

        Returns:
            str:
                A refined or "improved" user prompt string, suitable for feeding
                back into the LLM as a clearer instruction.

        Example:
            refined = await interpret(
                branch=my_branch, text="How do I do marketing analytics?",
                domain="marketing", style="detailed"
            )
            # refined might be "Explain step-by-step how to set up a marketing analytics
            #  pipeline to track campaign performance..."
        """
        from lionagi.operations.interpret.interpret import interpret

        return await interpret(
            self, text=text, domain=domain, style=style, **kwargs
        )

    async def instruct(
        self,
        instruct: Instruct,
        /,
        **kwargs,
    ):
        """
        A convenience method that chooses between `operate()` and `communicate()`
        based on the contents of an `Instruct` object.

        If the `Instruct` indicates tool usage or advanced response format,
        `operate()` is used. Otherwise, it defaults to `communicate()`.

        Args:
            instruct (Instruct):
                An object containing `instruction`, `guidance`, `context`, etc.
            **kwargs:
                Additional args forwarded to `operate()` or `communicate()`.

        Returns:
            Any:
                The result of the underlying call (structured object, raw text, etc.).
        """
        from lionagi.operations.instruct.instruct import instruct as _ins

        return await _ins(self, instruct, **kwargs)

    async def ReAct(
        self,
        instruct: Instruct | dict[str, Any],
        interpret: bool = False,
        tools: Any = None,
        tool_schemas: Any = None,
        response_format: type[BaseModel] = None,
        extension_allowed: bool = False,
        max_extensions: int = None,
        response_kwargs: dict | None = None,
        return_analysis: bool = False,
        analysis_model: iModel | None = None,
        **kwargs,
    ):
        """
        Performs a multi-step "ReAct" flow (inspired by the ReAct paradigm in LLM usage),
        which may include:
        1) Optionally interpreting the user's original instructions via `branch.interpret()`.
        2) Generating chain-of-thought analysis or reasoning using a specialized schema (`ReActAnalysis`).
        3) Optionally expanding the conversation multiple times if the analysis indicates more steps (extensions).
        4) Producing a final answer by invoking the branch's `instruct()` method.

        Args:
            branch (Branch):
                The active branch context that orchestrates messages, models, and actions.
            instruct (Instruct | dict[str, Any]):
                The user's instruction object or a dict with equivalent keys.
            interpret (bool, optional):
                If `True`, first interprets (`branch.interpret`) the instructions to refine them
                before proceeding. Defaults to `False`.
            tools (Any, optional):
                Tools to be made available for the ReAct process. If omitted or `None`,
                and if no `tool_schemas` are provided, it defaults to `True` (all tools).
            tool_schemas (Any, optional):
                Additional or custom schemas for tools if function calling is needed.
            response_format (type[BaseModel], optional):
                The final schema for the user-facing output after the ReAct expansions.
                If `None`, the output is raw text or an unstructured response.
            extension_allowed (bool, optional):
                Whether to allow multiple expansions if the analysis indicates more steps.
                Defaults to `False`.
            max_extensions (int | None, optional):
                The max number of expansions if `extension_allowed` is `True`.
                If omitted, no upper limit is enforced (other than logic).
            response_kwargs (dict | None, optional):
                Extra kwargs passed into the final `_instruct()` call that produces the
                final output. Defaults to `None`.
            return_analysis (bool, optional):
                If `True`, returns both the final output and the list of analysis objects
                produced throughout expansions. Defaults to `False`.
            analysis_model (iModel | None, optional):
                A custom LLM model for generating the ReAct analysis steps. If `None`,
                uses the branch's default `chat_model`.
            **kwargs:
                Additional keyword arguments passed into the initial `branch.operate()` call.

        Returns:
            Any | tuple[Any, list]:
                - If `return_analysis=False`, returns only the final output (which may be
                a raw string, dict, or structured model depending on `response_format`).
                - If `return_analysis=True`, returns a tuple of (final_output, list_of_analyses).
                The list_of_analyses is a sequence of the intermediate or extended
                ReActAnalysis objects.

        Notes:
            - Messages are automatically added to the branch context during the ReAct process.
            - If `max_extensions` is greater than 5, a warning is logged, and it is set to 5.
            - If `interpret=True`, the user instruction is replaced by the interpreted
            string before proceeding.
            - The expansions loop continues until either `analysis.extension_needed` is `False`
            or `extensions` (the remaining allowed expansions) is `0`.
        """
        from lionagi.operations.ReAct.ReAct import ReAct

        return await ReAct(
            self,
            instruct,
            interpret=interpret,
            tools=tools,
            tool_schemas=tool_schemas,
            response_format=response_format,
            extension_allowed=extension_allowed,
            max_extensions=max_extensions,
            response_kwargs=response_kwargs,
            return_analysis=return_analysis,
            analysis_model=analysis_model,
            **kwargs,
        )


# File: lionagi/session/branch.py
