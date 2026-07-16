#!/bin/sh
kill "$(cat producer.pid)"
kill "$(cat consumer.pid)"
