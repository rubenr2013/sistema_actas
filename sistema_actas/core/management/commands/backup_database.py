"""
Comando Django para crear backup de base de datos PostgreSQL

Uso:
    python manage.py backup_database
    
Crea un archivo .sql comprimido en la carpeta backups/
con formato: backup_YYYYMMDD_HHMMSS.sql.gz

Limpia automáticamente backups antiguos (> 30 días)
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
import subprocess
import gzip
from datetime import datetime, timedelta
from pathlib import Path


class Command(BaseCommand):
    help = 'Genera una copia de seguridad de la base de datos PostgreSQL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-days',
            type=int,
            default=30,
            help='Número de días de backups a mantener (default: 30)'
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

        # Crear directorio de backups
        backup_dir = settings.BASE_DIR / 'backups'
        backup_dir.mkdir(exist_ok=True)

        # Nombre del archivo de backup
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'backup_{timestamp}.sql'
        backup_filepath = backup_dir / backup_filename
        backup_compressed = backup_dir / f'{backup_filename}.gz'

        self.stdout.write('🔄 Generando backup de la base de datos...')
        self.stdout.write(f'   Base de datos: {db_name}')
        self.stdout.write(f'   Usuario: {db_user}')
        self.stdout.write(f'   Host: {db_host}:{db_port}')

        try:
            # Comando pg_dump
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password

            dump_command = [
                r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', db_name,
                '--no-owner',
                '--no-acl',
                '-f', str(backup_filepath)
            ]

            # Ejecutar pg_dump
            result = subprocess.run(
                dump_command,
                env=env,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise CommandError(f'❌ Error en pg_dump: {result.stderr}')

            # Comprimir el archivo
            self.stdout.write('🗜️  Comprimiendo backup...')
            with open(backup_filepath, 'rb') as f_in:
                with gzip.open(backup_compressed, 'wb') as f_out:
                    f_out.writelines(f_in)

            # Eliminar archivo sin comprimir
            backup_filepath.unlink()

            # Obtener tamaño del backup
            size_bytes = backup_compressed.stat().st_size
            size_mb = size_bytes / (1024 * 1024)

            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Backup generado exitosamente!'
                )
            )
            self.stdout.write(f'   Archivo: {backup_compressed.name}')
            self.stdout.write(f'   Tamaño: {size_mb:.2f} MB')
            self.stdout.write(f'   Ubicación: {backup_compressed}')

            # Limpiar backups antiguos
            keep_days = options['keep_days']
            self.cleanup_old_backups(backup_dir, keep_days)

        except FileNotFoundError:
            raise CommandError(
                '❌ Error: pg_dump no encontrado.\n'
                '   Instala PostgreSQL client tools:\n'
                '   - Windows: Instala PostgreSQL desde postgresql.org\n'
                '   - Linux: sudo apt-get install postgresql-client\n'
                '   - Mac: brew install postgresql'
            )
        except Exception as e:
            # Limpiar archivo parcial si existe
            if backup_filepath.exists():
                backup_filepath.unlink()
            if backup_compressed.exists():
                backup_compressed.unlink()
            raise CommandError(f'❌ Error durante el backup: {str(e)}')

    def cleanup_old_backups(self, backup_dir, keep_days):
        """Elimina backups más antiguos que keep_days"""
        self.stdout.write(f'\n🧹 Limpiando backups antiguos (> {keep_days} días)...')
        
        cutoff_date = datetime.now() - timedelta(days=keep_days)
        deleted_count = 0

        for backup_file in backup_dir.glob('backup_*.sql.gz'):
            # Extraer fecha del nombre del archivo
            try:
                # Formato: backup_YYYYMMDD_HHMMSS.sql.gz
                date_str = backup_file.stem.split('_')[1]  # YYYYMMDD
                backup_date = datetime.strptime(date_str, '%Y%m%d')
                
                if backup_date < cutoff_date:
                    backup_file.unlink()
                    deleted_count += 1
                    self.stdout.write(f'   🗑️  Eliminado: {backup_file.name}')
            except (ValueError, IndexError):
                # Si no se puede parsear la fecha, ignorar
                continue

        if deleted_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'   Eliminados {deleted_count} backup(s) antiguo(s)'
                )
            )
        else:
            self.stdout.write('   ✨ No hay backups antiguos para eliminar')