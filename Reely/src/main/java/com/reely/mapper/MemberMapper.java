package com.reely.mapper;

import com.reely.dto.MemberDto;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

@Mapper
public interface MemberMapper {
    List<MemberDto> findAll();

    Integer insertMember(MemberDto memberDto);

    Boolean findMemberByMemberId(MemberDto memberDto);
}
