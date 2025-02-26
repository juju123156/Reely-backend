package com.reely.serviceImpl;

import com.reely.dto.MemberDto;
import com.reely.security.CustomUserDetails;
import com.reely.mapper.MemberMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.util.ObjectUtils;

@Service
@Slf4j
public class UserDetailsServiceImpl implements UserDetailsService {

    private final MemberMapper memberMapper;

    @Autowired
    public UserDetailsServiceImpl(MemberMapper memberRepository) {
        this.memberMapper = memberRepository;
    }


    @Override
    public UserDetails loadUserByUsername(String memberId) throws UsernameNotFoundException {
        MemberDto member = memberMapper.findMemberInfo(memberId);

        if (ObjectUtils.isEmpty(member)) {
            log.error("사용자 정보를 찾을 수 없음: {}", memberId);
            throw new UsernameNotFoundException("사용자 아이디를 찾을 수 없습니다. " + memberId);
        }

        return new CustomUserDetails(member);
    }
}
