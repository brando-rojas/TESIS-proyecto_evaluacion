"""Revert column name to habilitar_rendimiento

Revision ID: 4bc73f2edb10
Revises: bea41c61ed08 # Asegúrate que este sea el ID de la migración ANTERIOR
Create Date: 2025-04-29 XX:XX:XX.XXXXXX # Fecha de creación

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4bc73f2edb10'
down_revision = 'bea41c61ed08' # ID de la migración que estamos corrigiendo/revirtiendo en parte
branch_labels = None
depends_on = None


def upgrade():
    print(f"Running upgrade {revision}: Revert column name to habilitar_rendimiento")
    # --- ÚNICA OPERACIÓN NECESARIA ---
    with op.batch_alter_table('configuracion_examen', schema=None) as batch_op:
        try:
            print("  Renaming column habilitar_pruebas_funcionales back to habilitar_rendimiento...")
            # Intentar renombrar. Quita existing_type si da problemas.
            batch_op.alter_column('habilitar_pruebas_funcionales', new_column_name='habilitar_rendimiento') #, existing_type=sa.BOOLEAN())
            print("  Column renamed successfully.")
        except Exception as e:
            # Podría fallar si la columna ya se llama habilitar_rendimiento (ej. si downgrade falló antes)
            # O si habilitar_pruebas_funcionales no existe.
            print(f"  WARNING: Could not rename column 'habilitar_pruebas_funcionales' to 'habilitar_rendimiento'. It might already be renamed or the source column doesn't exist. Error: {e}")
            # Continuar de todas formas, asumiendo que el estado deseado podría ya existir.
            pass
    print(f"Finished upgrade {revision}.")


def downgrade():
    print(f"Running downgrade {revision}: Revert column name back to habilitar_pruebas_funcionales")
    # --- OPERACIÓN INVERSA ---
    with op.batch_alter_table('configuracion_examen', schema=None) as batch_op:
        try:
            print("  Renaming column habilitar_rendimiento back to habilitar_pruebas_funcionales...")
            # Intentar renombrar de vuelta.
            batch_op.alter_column('habilitar_rendimiento', new_column_name='habilitar_pruebas_funcionales') #, existing_type=sa.BOOLEAN())
            print("  Column renamed successfully.")
        except Exception as e:
            # Podría fallar si la columna ya se llama habilitar_pruebas_funcionales
            # O si habilitar_rendimiento no existe.
            print(f"  WARNING: Could not rename column 'habilitar_rendimiento' to 'habilitar_pruebas_funcionales'. It might already be renamed or the source column doesn't exist. Error: {e}")
            pass
    print(f"Finished downgrade {revision}.")