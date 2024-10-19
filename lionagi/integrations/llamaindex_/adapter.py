from typing import Any, TypeVar

from lion_core.generic.base import RealElement
from lion_core.protocols.data_adapter import DataAdapter
from lionfuncs import check_import, to_dict, to_str

T = TypeVar("T", bound=RealElement)


class LlamaIndexNodeAdapter(DataAdapter):

    obj_key = "llamaindex"
    verbose = False
    config = None
    TextNode = check_import(
        "llama_index", module_name="core.schema", import_name="TextNode"
    )

    @classmethod
    def from_obj(
        cls,
        subj_cls: type[RealElement],
        obj: Any,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:

        dict_ = to_dict(obj, **kwargs)

        if "text" in dict_:
            dict_["content"] = dict_.pop("text")
        if "node_id" in dict_:
            dict_["llama_index_id"] = dict_.pop("node_id")
        if "lion_metadata" in dict_:
            dict_["metadata"] = to_dict(dict_.pop("lion_metadata"))
        if "class_name" in dict_:
            dict_["llama_index_class_name"] = dict_.pop("class_name")

        dict_["llama_index_metadata"] = dict_.pop("metadata", {})
        if "lion_metadata" in dict_["llama_index_metadata"]:
            if not isinstance(dict_["llama_index_metadata"], dict):
                try:
                    dict_["llama_index_metadata"] = to_dict(
                        dict_["llama_index_metadata"]
                    )
                    dict_["metadata"] = dict_["llama_index_metadata"].pop(
                        "lion_metadata", {}
                    )
                except Exception:
                    pass

        return dict_

    @classmethod
    def to_obj(
        cls,
        subj: T,
        /,
        **kwargs: Any,
    ) -> Any:

        dict_ = subj.to_dict(**kwargs)
        dict_["lion_metadata"] = to_dict(dict_.pop("metadata", {}))
        dict_["text"] = to_str(dict_.pop("content", ""))

        if "llama_index_id" in dict_:
            dict_["node_id"] = dict_.pop("llama_index_id")
        if "llama_index_metadata" in dict_:
            dict_["metadata"] = dict_.pop("llama_index_metadata")
        if "llama_index_class_name" in dict_:
            dict_["class_name"] = dict_.pop("llama_index_class_name")

        return cls.TextNode(**dict_)