#!/bin/bash
#
# @license https://www.gnu.org/licenses/gpl-3.0.txt GNU/GPL, see LICENSE

ASM_PATH={{ asm_path }}
ASM_DATA={{ asm_data }}

BACKUP_CNF=/etc/cron.daily/backup.d/asm.cnf
BACKUP_DIR=/srv/backups/asm

CKAN_URL={{ asm_ckan.url }}
API_KEY={{ asm_ckan.api_key }}

DB_HOST={{ asm_db.host }}
DB_PORT={{ asm_db.port }}
DB_NAME={{ asm_db.name }}
DB_USER={{ asm_db.user }}


# How many days worth of tarballs to keep around
num_days_to_keep=5

#----------------------------------------------------------
# ASM configured cron activies
#----------------------------------------------------------
/usr/bin/python $ASM_PATH/src/cron.py daily &> /var/log/cron/asm
/usr/bin/python $ASM_PATH/src/cron.py publish_3pty &>> /var/log/cron/asm

#----------------------------------------------------------
# Backups
#----------------------------------------------------------
now=`date +%s`
today=`date +%F`

# Dump the database
{% if   asm_db.type == 'POSTGRESQL' %}
PGPASSFILE=$BACKUP_CNF pg_dump -w -U $DB_USER -h $DB_HOST -d $DB_NAME -p $DB_PORT > $ASM_DATA/$DB_NAME.sql
{% elif asm_db.type == 'MYSQL' %}
mysqldump --defaults-extra-file=$BACKUP_CNF $DB_NAME > $ASM_DATA/$DB_NAME.sql
{% endif %}

cd $ASM_DATA
tar czf $today.tar.gz $DB_NAME.sql media
mv $today.tar.gz $BACKUP_DIR

# Purge any backup tarballs that are too old
cd $BACKUP_DIR
for file in `ls`
do
	atime=`stat -c %Y $file`
	if [ $(( $now - $atime >= $num_days_to_keep*24*60*60 )) = 1 ]
	then
		rm $file
	fi
done


#----------------------------------------------------------
# CKAN data upload
#----------------------------------------------------------
if [ ! -d $ASM_DATA/ckan/csv ]
	then mkdir $ASM_DATA/ckan/csv
fi

for file in `ls $ASM_DATA/ckan/sql`; do
    f=$(basename $file)
    resource_id=${f%.*}
{% if   asm_db.type == 'POSTGRESQL' %}
    PGPASSFILE=$BACKUP_CNF psql -w -U $DB_USER -h $DB_HOST -d $DB_NAME -p $DB_PORT < $ASM_DATA/ckan/sql/$file > $ASM_DATA/ckan/csv/$resource_id.csv
{% elif asm_db.type == 'MYSQL' %}
    # @todo Add MySQL support
    # No mysql support tested yet
{% endif %}
    curl -F "id=$resource_id" -F "upload=@$ASM_DATA/ckan/csv/$resource_id.csv;type=text/csv" -H "Authorization: $API_KEY" $CKAN_URL/api/3/action/resource_update
done
