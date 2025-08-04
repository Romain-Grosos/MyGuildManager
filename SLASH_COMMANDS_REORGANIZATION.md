# Réorganisation des Slash Commandes Discord Bot

## État actuel des commandes

### Commandes par fichier

#### **absence.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `absence_add` | Marquer un membre absent | manage_guild |

#### **contract.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `contract` | Sélectionner et publier des contrats de guilde | manage_messages |
| `contract_delete` | Supprimer le contrat de guilde | manage_messages |

#### **core.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `app_initialize` | Initialiser une guilde dans le système | administrator |
| `app_modify` | Modifier les paramètres de guilde existants | administrator |
| `app_reset` | Réinitialiser la configuration de guilde | administrator |

#### **epic_items_scraper.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `epic_items` | Voir les objets Épiques T2 de Throne and Liberty | - |

#### **guild_init.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `discord_setup` | Initialiser le serveur Discord avec rôles et canaux | administrator |

#### **guild_members.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `gs` | Mettre à jour le gear score (GS) | - |
| `weapons` | Mettre à jour la combinaison d'armes | - |
| `build` | Mettre à jour l'URL du build | - |
| `username` | Mettre à jour le nom d'utilisateur | - |
| `maj_roster` | Mise à jour optimisée du roster | manage_roles |
| `show_build` | Afficher le build d'un autre membre | - |
| `notify_profile` | Envoyer des notifications aux profils incomplets | manage_roles |
| `config_roster` | Configurer les tailles idéales du roster par classe | administrator |
| `change_language` | Changer la langue préférée | - |

#### **guild_ptb.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| `ptb_init` | Initialiser la configuration PTB | manage_guild |

#### **loot_wishlist.py**
| Commande | Description | Permissions |
|----------|-------------|-------------|
| **Groupe wishlist:** | | |
| `wishlist add_item` | Ajouter un objet Épique T2 à la wishlist | - |
| `wishlist remove_item` | Retirer un objet de la wishlist | - |
| `wishlist show_items` | Voir la wishlist actuelle | - |
| `wishlist_admin` | [MOD] Voir les statistiques globales des wishlists | manage_guild |

## Proposition de réorganisation par groupes

### 1. **admin** - Commandes d'administration système
*Pour les administrateurs du serveur uniquement*

| Commande | Description | Fichier source |
|----------|-------------|----------------|
| `admin app_initialize` | Initialiser une guilde dans le système | core.py |
| `admin app_modify` | Modifier les paramètres de guilde | core.py |
| `admin app_reset` | Réinitialiser la configuration | core.py |
| `admin discord_setup` | Initialiser le serveur Discord | guild_init.py |

### 2. **guild** - Gestion de la guilde
*Pour les modérateurs et officiers*

| Commande | Description | Fichier source |
|----------|-------------|----------------|
| `guild config_roster` | Configurer les tailles idéales du roster | guild_members.py |
| `guild maj_roster` | Mise à jour du roster | guild_members.py |
| `guild notify_profile` | Notifier les profils incomplets | guild_members.py |
| `guild ptb_init` | Initialiser la configuration PTB | guild_ptb.py |
| `guild contract` | Gérer les contrats de guilde | contract.py |
| `guild contract_delete` | Supprimer le contrat | contract.py |
| `guild absence_add` | Marquer un membre absent | absence.py |

### 3. **profile** - Gestion du profil membre
*Pour tous les membres*

| Commande | Description | Fichier source |
|----------|-------------|----------------|
| `profile gs` | Mettre à jour le gear score | guild_members.py |
| `profile weapons` | Mettre à jour les armes | guild_members.py |
| `profile build` | Mettre à jour l'URL du build | guild_members.py |
| `profile username` | Mettre à jour le nom | guild_members.py |
| `profile language` | Changer la langue | guild_members.py |

### 4. **wishlist** - Système de wishlist
*Pour tous les membres*

| Commande | Description | Fichier source |
|----------|-------------|----------------|
| `wishlist add` | Ajouter un objet à la wishlist | loot_wishlist.py |
| `wishlist remove` | Retirer un objet | loot_wishlist.py |
| `wishlist show` | Voir sa wishlist | loot_wishlist.py |
| `wishlist admin` | [MOD] Statistiques globales | loot_wishlist.py |

### 5. **info** - Commandes d'information
*Pour tous les membres*

| Commande | Description | Fichier source |
|----------|-------------|----------------|
| `info build` | Voir le build d'un membre | guild_members.py |
| `info epic_items` | Consulter les objets épiques | epic_items_scraper.py |

## Avantages de cette réorganisation

1. **Clarté** : Les commandes sont regroupées par domaine fonctionnel
2. **Permissions** : Séparation claire entre admin/modération/utilisateur
3. **Navigation** : Plus facile de trouver la bonne commande
4. **Cohérence** : Structure uniforme avec préfixes de groupe
5. **Évolutivité** : Facile d'ajouter de nouvelles commandes dans les groupes existants

## Prochaines étapes

1. Implémenter les groupes de commandes dans le code
2. Migrer les commandes existantes vers les nouveaux groupes
3. Mettre à jour les permissions et descriptions
4. Tester toutes les commandes migrées
5. Mettre à jour la documentation utilisateur