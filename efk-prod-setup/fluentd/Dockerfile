FROM fluent/fluentd:v1.16-1

USER root

# Install Elasticsearch plugin and other useful plugins
RUN gem install fluent-plugin-elasticsearch --no-document \
    && gem install fluent-plugin-docker_metadata_filter --no-document \
    && gem install fluent-plugin-concat --no-document \
    && gem install fluent-plugin-multi-format-parser --no-document

USER root
