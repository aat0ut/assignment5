from enum import Enum
from pydantic import BaseModel, Field

class Category(str, Enum):
    billing = "billing"
    bug = "bug"
    feature = "feature"
    other = "other"

class Urgency(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"

class TriageInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

class TriageOutput(BaseModel):
    category: Category
    urgency: Urgency
    confidence: float = Field(..., ge=0.0, le=1.0)
