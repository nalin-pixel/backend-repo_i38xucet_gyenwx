"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal

class Account(BaseModel):
    """
    Accounts collection for authentication
    Collection name: "account"
    """
    email: EmailStr = Field(..., description="User email (unique)")
    hashed_password: str = Field(..., description="Hashed password")
    name: Optional[str] = Field(None, description="Display name")
    plan: Literal['individual','team'] = Field('individual', description="Account type")
    provider: Literal['password','github'] = Field('password', description="Auth provider")
    github_username: Optional[str] = None
    avatar_url: Optional[str] = None

class RepoConnection(BaseModel):
    """
    Repository connections
    Collection name: "repoconnection"
    """
    account_id: str = Field(..., description="Owner account id")
    provider: Literal['github'] = 'github'
    repo_full_name: str = Field(..., description="owner/repo")
    installation_id: Optional[int] = None
    default_branch: Optional[str] = None

# Example existing schemas kept for reference
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = Field(None, ge=0, le=120)
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
