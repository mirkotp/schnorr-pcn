FROM mirkotp/charm-crypto:1.0
WORKDIR /app
COPY ./src .

CMD python pcn_test.py