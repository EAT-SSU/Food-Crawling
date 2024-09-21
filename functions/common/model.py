from pydantic import BaseModel
from typing import List
class MenuExtraction(BaseModel):
    menus: List[str]
