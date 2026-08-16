"""Camada de leitura: as únicas partes do Supervisor que tocam o mundo.

Regra: readers só leem. Nenhum reader escreve em banco, arquivo, tmux ou
systemd. Checks recebem linhas prontas e não conhecem conexão nenhuma — é o
que permite testar a lógica sem banco.
"""
