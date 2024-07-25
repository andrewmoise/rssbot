#!/bin/bash

while true; do
    date
    python3 fetch_and_post.py || break
    sleep 60
done
