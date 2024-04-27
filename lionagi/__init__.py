"""
lionagi is an intelligent automation framework.
"""

import logging
from .version import __version__
from dotenv import load_dotenv

from .core import direct
from .core.branch.branch import Branch
from .core.session.session import Session
from .core.tool.tool_manager import func_to_tool
from .integrations.provider.services import Services
from .integrations.chunker.chunk import chunk
from .integrations.loader.load import load
from .experimental.work import Form, Report, Worker, work



logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
load_dotenv()
