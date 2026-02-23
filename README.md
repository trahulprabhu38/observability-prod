# prometheus-prod


#docker metrics:

vi /etc/docker/daemon.json
{
    "metrics-addr":"127.0.0.1:9323",
    "experimental":true
}
sudo systemctl restart docker

