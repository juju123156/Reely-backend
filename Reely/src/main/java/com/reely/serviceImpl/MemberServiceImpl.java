package com.reely.serviceImpl;

import com.reely.dto.EmailDto;
import com.reely.dto.MemberDto;
import com.reely.mapper.MemberMapper;
import com.reely.service.MemberService;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
@Transactional
public class MemberServiceImpl implements MemberService {

    private final MemberMapper memberMapper;

    private final BCryptPasswordEncoder bCryptPasswordEncoder;

    @Autowired
    public MemberServiceImpl(MemberMapper memberMapper, BCryptPasswordEncoder bCryptPasswordEncoder) {
        this.memberMapper = memberMapper;
        this.bCryptPasswordEncoder = bCryptPasswordEncoder;
    }

    @Override
    public Boolean existsByMemberId(MemberDto memberDto) {
        return memberMapper.existsByMemberId(memberDto);
    }

    @Override
    @Transactional
    public Integer insertMember(MemberDto memberDto) {
        memberDto.setMemberPwd(bCryptPasswordEncoder.encode(memberDto.getMemberPwd())); // 암호화
        return memberMapper.insertMember(memberDto);
    }

    @Override
    public Boolean existsByMemberEmail(MemberDto memberDto) {
        return memberMapper.existsByMemberEmail(memberDto);
    }

    @Override
    public MemberDto findMemberIdByMemberEmail(EmailDto emailDto) {
        return memberMapper.findMemberIdByMemberEmail(emailDto);
    }
}