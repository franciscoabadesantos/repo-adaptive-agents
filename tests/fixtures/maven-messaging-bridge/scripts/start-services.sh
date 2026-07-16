#!/bin/sh
java -jar producer.jar &
echo "$!" > producer.pid
java -jar consumer.jar &
echo "$!" > consumer.pid
