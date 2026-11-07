ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app /app
COPY rootfs /

RUN chmod a+x /etc/services.d/bridge/run /etc/services.d/bridge/finish

EXPOSE 8099
