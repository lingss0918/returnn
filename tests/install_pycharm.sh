#!/usr/bin/env bash

set -xe

name="pycharm-community-2018.3.5"
fn="$name.tar.gz"

wget -c "https://download.jetbrains.com/python/$fn"

tar -xzvf $fn
test -d $name
mv $name pycharm
