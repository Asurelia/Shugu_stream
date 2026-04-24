"""Pydantic schemas groupes par feature — decouples des modeles ORM.

Conviction Phase C : separer les schemas d'echange (Pydantic) des modeles
DB (SQLAlchemy) permet de faire evoluer l'API independamment du schema
physique. Ex : ajouter un champ calcule cote Pydantic sans toucher la DB.
"""
