# 📋 Évolutions futures du bot

## 📊 Métriques et monitoring

### Export Prometheus (priorité moyenne)
- **Objectif** : Exposer les métriques internes via endpoint `/metrics`
- **Métriques cibles** :
  - `commands_total{guild,command}` : Nombre de commandes exécutées
  - `db_queries_duration_seconds{query_type}` : Temps d'exécution des requêtes
  - `cache_hit_ratio` : Ratio de hit/miss des caches
  - `circuit_breaker_state{service}` : État des circuit breakers
  - `active_connections` : Connexions DB actives

### Métriques DB détaillées (priorité basse)
- **Objectif** : Enrichir les statistiques de performance DB
- **Nouvelles métriques** :
  - Top 10 des requêtes les plus lentes
  - Taux d'utilisation du pool de connexions
  - Nombre d'échecs par type d'erreur
  - Histogramme des temps de réponse

## 🔧 Améliorations techniques

### Migration aiomysql (priorité faible)
- **Objectif** : Remplacement du driver MariaDB synchrone
- **Avantages** :
  - Connexions natives async (pas de thread pool)
  - Meilleure performance sous forte charge
  - Réduction de l'overhead mémoire
- **Impact technique** :
  - Refactoring complet du module `db.py`
  - Installation côté serveur : `pip uninstall mariadb && pip install aiomysql==0.1.1`
  - Aucune modification DB requise (même protocole MySQL/MariaDB)
- **Justification report** : Trafic actuel modéré, gains visibles surtout >100 req/s

## 📝 Décisions architecturales

### Multi-instances
- **Statut** : Non prévu
- **Justification** : Bot single-instance, pas de besoin de cooldown partagé Redis

### Migrations DB
- **Statut** : Non prévu  
- **Justification** : Fichier SQL maintenu manuellement, environnement contrôlé

## 🎯 Prochaines étapes
1. Finaliser les corrections de sécurité (TTL cache ✅, backoff ✅, logs ✅)
2. Monitorer la stabilité en production
3. Évaluer l'export Prometheus selon les besoins opérationnels