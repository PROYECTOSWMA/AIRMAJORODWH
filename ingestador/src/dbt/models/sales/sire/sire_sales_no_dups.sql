{{ config(materialized='ephemeral')}}
{{ removedups('sire_sales', 'car_sunat') }}
