static uint32_t reference_sum16(uint32_t sum,const uint8_t *p,unsigned n) {
    while(n>=2) { sum+=be16(p); p+=2; n-=2; }
    if(n) sum+=(uint32_t)*p<<8;
    return sum;
}
