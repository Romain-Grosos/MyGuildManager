# Configuration Base de Données

## Optimisations MySQL/MariaDB pour Discord Bot

### GROUP_CONCAT_MAX_LEN pour Guildes Massives

**Problème** : Pour les guildes avec de nombreux membres, la vue `loot_wishlist_stats` utilise `GROUP_CONCAT` pour lister les utilisateurs intéressés par chaque item. La limite par défaut (1024 caractères) peut tronquer la liste.

**Solution** : Augmenter la limite `GROUP_CONCAT_MAX_LEN`

#### Configuration Globale (Recommandée)

```sql
-- Nécessite privilèges SUPER
SET GLOBAL group_concat_max_len = 32768;
```

#### Configuration Permanente (my.cnf)

Ajouter dans le fichier de configuration MySQL/MariaDB :

**Linux** : `/etc/mysql/my.cnf` ou `/etc/mysql/mysql.conf.d/mysqld.cnf`
**Windows** : `C:\ProgramData\MySQL\MySQL Server X.X\my.ini`

```ini
[mysqld]
group_concat_max_len = 32768
```

Puis redémarrer le service MySQL/MariaDB.

#### Vérification

```sql
SELECT @@global.group_concat_max_len, @@session.group_concat_max_len;
```

**Valeurs attendues** :
- Défaut : 1024
- Recommandée : 32768 (support ~1000 utilisateurs par item)

### Index et Contraintes

Les migrations suivantes ont été appliquées pour optimiser les performances :

- `UNIQUE KEY uniq_wishlist (guild_id, user_id, item_id)` - Prévention doublons
- `KEY idx_wishlist_guild_item (guild_id, item_id)` - Optimisation requêtes par guild/item  
- `KEY idx_wishlist_user (guild_id, user_id)` - Optimisation requêtes par utilisateur
- Contraintes de validation sur `item_name` et `item_id`

### Surveillance

Monitorer la taille des résultats GROUP_CONCAT :

```sql
SELECT 
    item_name,
    demand_count,
    LENGTH(interested_users) as user_list_length,
    CASE 
        WHEN LENGTH(interested_users) >= @@global.group_concat_max_len 
        THEN 'TRUNCATED!' 
        ELSE 'OK' 
    END as status
FROM loot_wishlist_stats 
WHERE guild_id = YOUR_GUILD_ID
ORDER BY LENGTH(interested_users) DESC
LIMIT 10;
```

### Dépannage

**Symptômes de troncature** :
- Listes d'utilisateurs incomplètes dans les statistiques de wishlist
- Nombre d'utilisateurs affiché inférieur au réel

**Diagnostic** :
```sql
-- Vérifier la configuration actuelle
SHOW VARIABLES LIKE 'group_concat_max_len';

-- Identifier les items avec de longues listes
SELECT item_name, LENGTH(interested_users) as list_length 
FROM loot_wishlist_stats 
WHERE LENGTH(interested_users) > 1000;
```