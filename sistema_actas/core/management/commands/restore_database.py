"""
Comando Django para restaurar backup de base de datos PostgreSQL

Uso:
    python manage.py restore_database backups/backup_20251209_150000.sql.gz
    python manage.py restore_database backups/backup_20251209_150000.sql.gz --no-confirm
    
Restaura la base de datos desde un archivo .sql o .sql.gz

ADVERTENCIA: Este comando BORRARÁ todos los datos actuales y los 
reemplazará con los datos del backup.
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
import subprocess
import gzip
from pathlib import Path


class Command(BaseCommand):
    help = 'Restaura la base de datos desde un archivo de backup'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            type=str,
            help='Ruta al archivo de backup (.sql o .sql.gz)'
        )
        parser.add_argument(
            '--no-confirm',
            action='store_true',
            help='No solicitar confirmación (usar con precaución)'
        )

    def handle(self, *args, **options):
        # Obtener configuración de la base de datos
        db_config = settings.DATABASES['default']
        
        # Validar que sea PostgreSQL
        if 'postgresql' not in db_config['ENGINE']:
            raise CommandError(
                '⚠️  Este comando solo funciona con PostgreSQL. '
                f'Tu base de datos es: {db_config["ENGINE"]}'
            )

        db_name = db_config['NAME']
        db_user = db_config['USER']
        db_password = db_config['PASSWORD']
        db_host = db_config['HOST'] or 'localhost'
        db_port = db_config['PORT'] or '5432'

        # Obtener ruta del archivo de backup
        backup_file = Path(options['backup_file'])
        
        # Validar que el archivo existe
        if not backup_file.exists():
            raise CommandError(f'❌ Error: El archivo no existe: {backup_file}')

        # Validar extensión
        if backup_file.suffix not in ['.sql', '.gz']:
            raise CommandError(
                f'❌ Error: Formato de archivo no válido: {backup_file.suffix}\n'
                '   Formatos aceptados: .sql, .sql.gz'
            )

        self.stdout.write('📋 Información del restore:')
        self.stdout.write(f'   Archivo: {backup_file.name}')
        self.stdout.write(f'   Base de datos: {db_name}')
        self.stdout.write(f'   Usuario: {db_user}')
        self.stdout.write(f'   Host: {db_host}:{db_port}')

        # Solicitar confirmación
        if not options['no_confirm']:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  ADVERTENCIA: Esta operación BORRARÁ todos los datos actuales\n'
                    '   y los reemplazará con los datos del backup.\n'
                )
            )
            confirm = input('¿Estás seguro de continuar? (escribe "SI" para confirmar): ')
            if confirm != 'SI':
                self.stdout.write(self.style.ERROR('❌ Operación cancelada'))
                return

        try:
            # Descomprimir si es necesario
            if backup_file.suffix == '.gz':
                self.stdout.write('\n🗜️  Descomprimiendo backup...')
                temp_sql = backup_file.parent / backup_file.stem
                
                with gzip.open(backup_file, 'rb') as f_in:
                    with open(temp_sql, 'wb') as f_out:
                        f_out.write(f_in.read())
                
                sql_file = temp_sql
            else:
                sql_file = backup_file

            self.stdout.write('\n🔄 Restaurando base de datos...')
            
            # Comando psql para restaurar
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password

            # Primero, eliminar y recrear la base de datos
            self.stdout.write('   1. Limpiando base de datos actual...')
            
            # Conectar a la base de datos 'postgres' para poder borrar la base de datos objetivo
            drop_db_command = [
                r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', 'postgres',
                '-c', f'DROP DATABASE IF EXISTS {db_name};'
            ]
            
            result = subprocess.run(
                drop_db_command,
                env=env,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise CommandError(f'❌ Error al eliminar base de datos: {result.stderr}')

            # Crear la base de datos nuevamente
            self.stdout.write('   2. Creando base de datos limpia...')
            
            create_db_command = [
                r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', 'postgres',
                '-c', f'CREATE DATABASE {db_name};'
            ]
            
            result = subprocess.run(
                create_db_command,
                env=env,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise CommandError(f'❌ Error al crear base de datos: {result.stderr}')

            # Restaurar desde el backup
            self.stdout.write('   3. Restaurando datos desde backup...')
            
            restore_command = [
                r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', db_name,
                '-f', str(sql_file)
            ]

            result = subprocess.run(
                restore_command,
                env=env,
                capture_output=True,
                text=True
            )

            # Limpiar archivo temporal si se descomprimió
            if backup_file.suffix == '.gz' and temp_sql.exists():
                temp_sql.unlink()

            if result.returncode != 0:
                # No necesariamente es un error, pg_dump puede generar warnings
                if 'ERROR' in result.stderr:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️  Advertencias durante restore: {result.stderr}')
                    )

            self.stdout.write(
                self.style.SUCCESS(
                    '\n✅ Base de datos restaurada exitosamente!'
                )
            )
            self.stdout.write(
                '\n💡 Recomendación: Ejecuta las migraciones para asegurar que '
                'el esquema está actualizado:'
            )
            self.stdout.write('   python manage.py migrate')

        except FileNotFoundError:
            raise CommandError(
                '❌ Error: psql no encontrado.\n'
                '   Instala PostgreSQL client tools:\n'
                '   - Windows: Instala PostgreSQL desde postgresql.org\n'
                '   - Linux: sudo apt-get install postgresql-client\n'
                '   - Mac: brew install postgresql'
            )
        except Exception as e:
            # Limpiar archivo temporal si existe
            if backup_file.suffix == '.gz':
                temp_sql = backup_file.parent / backup_file.stem
                if temp_sql.exists():
                    temp_sql.unlink()
            raise CommandError(f'❌ Error durante el restore: {str(e)}')