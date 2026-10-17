{{ config(materialized='ephemeral') }}
{{ removedups('sire_purchs', 'car_sunat') }}